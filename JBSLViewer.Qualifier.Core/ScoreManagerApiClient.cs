using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using JBSLViewer.Qualifier.Core.Contracts;
using Newtonsoft.Json.Linq;
namespace JBSLViewer.Qualifier.Core {
    public sealed class ApiException : Exception {
        public int HttpStatus { get; private set; }
        public string Code { get; private set; }
        public bool Retryable { get; private set; }
        public string RequestId { get; private set; }
        public TimeSpan? RetryAfter { get; private set; }
        public ApiException(int status,string code,bool retryable,string requestId=null,TimeSpan? retryAfter=null) : base(code) { HttpStatus=status;Code=code;Retryable=retryable;RequestId=requestId;RetryAfter=retryAfter; }
    }
    public sealed class ScoreSession : IDisposable {
        public ScoreServerEndpoint Endpoint { get; internal set; }
        public string OwnerSid { get; internal set; }
        public long Generation { get; internal set; }
        public CookieContainer Cookies { get; internal set; }
        public HttpClient Http { get; internal set; }
        public AuthResponse Authentication { get; internal set; }
        public void Dispose() { Http.Dispose(); }
    }
    public class ScoreManagerApiClient {
        private readonly Func<CookieContainer,HttpMessageHandler> _handlerFactory;
        public TimeSpan RequestTimeout { get; set; } = TimeSpan.FromSeconds(30);
        public ScoreManagerApiClient(Func<CookieContainer,HttpMessageHandler> handlerFactory=null) { _handlerFactory=handlerFactory; }
        public ScoreSession CreateSession(ScoreServerEndpoint endpoint,string sid,long generation) {
            var cookies=new CookieContainer();
            var handler=_handlerFactory!=null?_handlerFactory(cookies):new HttpClientHandler { CookieContainer=cookies,UseCookies=true,AllowAutoRedirect=false,UseProxy=false };
            var http=new HttpClient(handler) { Timeout=Timeout.InfiniteTimeSpan }; http.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json")); http.DefaultRequestHeaders.UserAgent.ParseAdd("JBSLViewer-Qualifier/1.0");
            return new ScoreSession {Endpoint=endpoint,OwnerSid=sid,Generation=generation,Cookies=cookies,Http=http};
        }
        private async Task<string> SendAsync(ScoreSession session,HttpMethod method,string path,HttpContent content,string key,CancellationToken token,bool bounded=true,Action<int> responseStatus=null) {
            using(var timeout=CancellationTokenSource.CreateLinkedTokenSource(token)) {
                // Keep the reserve transport alive beyond the UI timeout to observe late success,
                // but eventually retry an unresponsive socket with the same process-local key.
                timeout.CancelAfter(bounded?RequestTimeout:TimeSpan.FromMilliseconds(Math.Max(1000,RequestTimeout.TotalMilliseconds*3)));
                using(var request=new HttpRequestMessage(method,session.Endpoint.Resolve(path))) {
                    request.Content=content; if(key!=null) request.Headers.Add("Idempotency-Key",key);
                    using(var response=await session.Http.SendAsync(request,timeout.Token).ConfigureAwait(false)) {
                        responseStatus?.Invoke((int)response.StatusCode);
                        var body=await response.Content.ReadAsStringAsync().ConfigureAwait(false);
                        if(!response.IsSuccessStatusCode) {
                            var code="http_"+(int)response.StatusCode; bool retryable=(int)response.StatusCode>=500 || (int)response.StatusCode==429; string id=null;
                            try { var o=StrictJson.Object(body); var e=o["error"] as JObject ?? o; code=e["code"]?.Value<string>()??code; retryable=e["retryable"]?.Value<bool>()??retryable; id=o["requestId"]?.Value<string>()??e["requestId"]?.Value<string>(); } catch { }
                            TimeSpan? retry=response.Headers.RetryAfter?.Delta; if(!retry.HasValue && response.Headers.RetryAfter?.Date!=null) retry=response.Headers.RetryAfter.Date.Value-DateTimeOffset.UtcNow;
                            throw new ApiException((int)response.StatusCode,code,retryable,id,retry);
                        }
                        return body;
                    }
                }
            }
        }
        public virtual async Task<AuthResponse> GetMeAsync(ScoreSession session,CancellationToken token) { return StrictJson.ParseAuth(await SendAsync(session,HttpMethod.Get,"api/v1/auth/me",null,null,token).ConfigureAwait(false)); }
        public virtual async Task<AuthResponse> AuthenticateAsync(ScoreSession session,PlatformTicket ticket,CancellationToken token) {
            if(ticket==null || (ticket.Provider!="steamTicket" && ticket.Provider!="oculusTicket") || string.IsNullOrEmpty(ticket.Ticket)) throw new ApiException(401,"ticket_unavailable",false);
            var form=new FormUrlEncodedContent(new Dictionary<string,string>{{"ticket",ticket.Ticket},{"provider",ticket.Provider},{"returnUrl","/"}});
            return StrictJson.ParseAuth(await SendAsync(session,HttpMethod.Post,"api/v1/auth/session",form,null,token).ConfigureAwait(false));
        }
        public virtual Task LogoutAsync(ScoreSession session,CancellationToken token) { return SendAsync(session,HttpMethod.Delete,"api/v1/auth/session",null,null,token); }
        public virtual async Task<StatusResponse> GetStatusAsync(ScoreSession session,GateToken gate,CancellationToken token) {
            var q="api/v1/qualifiers/status?leagueId="+gate.LeagueId+"&hash="+Uri.EscapeDataString(gate.Map.Hash)+"&characteristic="+Uri.EscapeDataString(gate.Map.Characteristic)+"&difficulty="+Uri.EscapeDataString(gate.Map.Difficulty)+"&jbslRevision="+Uri.EscapeDataString(gate.Revision);
            return StrictJson.ParseStatus(await SendAsync(session,HttpMethod.Get,q,null,null,token).ConfigureAwait(false));
        }
        public virtual async Task<ReserveResponse> ReserveAsync(ScoreSession session,ReserveRequest request,string key,CancellationToken token) {
            // Coordinator controls the UI timeout separately; a response arriving after it must still be processed.
            int status=0;var raw=await SendAsync(session,HttpMethod.Post,"api/v1/qualifiers/challenges",Json(request),key,token,false,value=>status=value).ConfigureAwait(false);var response=StrictJson.ParseReserve(raw);response.ResponseHttpStatus=status;response.RawJson=raw;return response;
        }
        public virtual Task StartedAsync(ScoreSession session,string id,StartedRequest request,CancellationToken token) { return SendAsync(session,HttpMethod.Post,"api/v1/qualifiers/challenges/"+Uri.EscapeDataString(id)+"/started",Json(request),null,token); }
        public virtual async Task<ResultResponse> SendResultAsync(ScoreSession session,string challengeId,string metadata,byte[] gzip,string key,CancellationToken token) {
            var multipart=new MultipartFormDataContent(); var json=new StringContent(metadata,Encoding.UTF8,"application/json"); multipart.Add(json,"metadata");
            if(gzip!=null) { if(gzip.Length>16*1024*1024) { multipart.Dispose(); throw new ApiException(422,"replay_too_large",false); } var replay=new ByteArrayContent(gzip); replay.Headers.ContentType=new MediaTypeHeaderValue("application/gzip"); multipart.Add(replay,"replay","replay.bsor.gz"); }
            var raw=await SendAsync(session,HttpMethod.Put,"api/v1/qualifiers/challenges/"+Uri.EscapeDataString(challengeId)+"/result",multipart,key,token).ConfigureAwait(false);var result=StrictJson.ParseResult(raw);result.RawJson=raw;
            if(result.ChallengeId!=challengeId) throw new FormatException("Mismatched result response"); return result;
        }
        private static HttpContent Json(object data) { return new StringContent(StrictJson.Serialize(data),Encoding.UTF8,"application/json"); }
    }
}

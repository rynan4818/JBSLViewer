using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using JBSLViewer.Qualifier.Core.Contracts;
namespace JBSLViewer.Qualifier.Core {
    public sealed class AuthenticationSession : IDisposable {
        private readonly ScoreManagerApiClient _api;
        private readonly IPlatformTicketProvider _provider;
        private readonly IClock _clock;
        private readonly object _sync=new object();
        private readonly List<ScoreSession> _retired=new List<ScoreSession>();
        private ScoreSession _current;
        private Task<ScoreSession> _flight;
        private bool _awaitingAuth;
        public long Generation { get; private set; }
        public string CurrentSid { get { return _provider.CurrentSid; } }
        public ScoreServerEndpoint Endpoint { get; private set; }
        public event Action Changed;
        public AuthenticationSession(ScoreManagerApiClient api,IPlatformTicketProvider provider,IClock clock=null) { _api=api;_provider=provider;_clock=clock??new SystemClock(); }
        public void Configure(string url,bool allowDevelopmentHttp) {
            var endpoint=ScoreServerEndpoint.Parse(url,allowDevelopmentHttp); bool changed=false;
            lock(_sync) {
                if(_current==null || _current.OwnerSid!=CurrentSid || Endpoint.NormalizedUrl!=endpoint.NormalizedUrl) {
                    if(_current!=null) _retired.Add(_current);
                    Endpoint=endpoint; Generation++; _current=_api.CreateSession(endpoint,CurrentSid,Generation); _flight=null;_awaitingAuth=false;changed=true;
                }
            }
            if(changed) Changed?.Invoke();
        }
        public void RefreshIdentity() { if(Endpoint!=null) Configure(Endpoint.NormalizedUrl,Endpoint.Uri.Scheme=="http"); }
        public void ClearConfiguration() { lock(_sync) { if(_current!=null) _retired.Add(_current);_current=null;Endpoint=null;Generation++;_flight=null;_awaitingAuth=false; } Changed?.Invoke(); }
        public bool IsCurrent(ScoreSession session) { lock(_sync) return session!=null && ReferenceEquals(_current,session) && session.OwnerSid==CurrentSid && session.Generation==Generation; }
        public bool IsAuthenticated(ScoreSession session) { return IsCurrent(session) && Valid(session.Authentication,session.OwnerSid); }
        private bool Valid(AuthResponse a,string sid) { return a!=null && a.Authenticated && a.User!=null && a.User.Sid==sid && !string.IsNullOrWhiteSpace(sid) && a.ExpiresAt>_clock.UtcNow; }
        public Task<ScoreSession> EnsureAsync(bool explicitRetry=false,CancellationToken token=default(CancellationToken)) {
            RefreshIdentity();
            lock(_sync) {
                if(_current==null || string.IsNullOrWhiteSpace(CurrentSid)) return Task.FromResult<ScoreSession>(null);
                if(_flight!=null && !_flight.IsCompleted) return _flight;
                if(_awaitingAuth && !explicitRetry) return Task.FromResult<ScoreSession>(null);
                if(!explicitRetry && Valid(_current.Authentication,CurrentSid)) return Task.FromResult(_current);
                _awaitingAuth=false;
                _flight=AuthenticateCoreAsync(_current,explicitRetry,token); return _flight;
            }
        }
        private async Task<ScoreSession> AuthenticateCoreAsync(ScoreSession original,bool force,CancellationToken token) {
            // Yield so the single-flight task is installed before platform callbacks can finish synchronously.
            await Task.Yield();
            ScoreSession session=original;
            try {
                AuthResponse response=null;
                if(!force && session.Cookies.Count>0) { try { response=await _api.GetMeAsync(session,token).ConfigureAwait(false); } catch(ApiException ex) { if(ex.HttpStatus!=401) throw; } }
                if(!Valid(response,session.OwnerSid)) {
                    lock(_sync) { if(!IsCurrent(session)) return null; _retired.Add(session); _current=_api.CreateSession(Endpoint,CurrentSid,Generation); session=_current; }
                    var ticket=await _provider.GetTicketAsync(token).ConfigureAwait(false);
                    if(!IsCurrent(session)) return null;
                    try { response=await _api.AuthenticateAsync(session,ticket,token).ConfigureAwait(false); } finally { if(ticket!=null) ticket.Ticket=null; }
                }
                lock(_sync) {
                    if(!IsCurrent(session)) return null;
                    if(!Valid(response,session.OwnerSid)) { _awaitingAuth=true;session.Authentication=null;return null; }
                    session.Authentication=response; return session;
                }
            } catch { lock(_sync) if(IsCurrent(session)) { _awaitingAuth=true;session.Authentication=null; } return null; }
        }
        public void Invalidate() { lock(_sync) if(_current!=null) { _current.Authentication=null; } }
        public void AwaitAuthentication() { lock(_sync) { _awaitingAuth=true;if(_current!=null) _current.Authentication=null; } }
        public async Task LogoutAsync() { ScoreSession s; lock(_sync) s=_current; if(s!=null) try { await _api.LogoutAsync(s,CancellationToken.None).ConfigureAwait(false); } finally { lock(_sync) { _awaitingAuth=true; s.Authentication=null; } } }
        public void Dispose() { lock(_sync) { _current?.Dispose(); foreach(var s in _retired) s.Dispose(); _retired.Clear(); } }
    }
}

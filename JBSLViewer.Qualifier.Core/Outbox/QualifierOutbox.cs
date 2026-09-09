using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using JBSLViewer.Qualifier.Core.Contracts;
namespace JBSLViewer.Qualifier.Core.Outbox {
    public sealed class QualifierOutbox {
        private readonly OutboxStore _store;private readonly ScoreManagerApiClient _api;private readonly AuthenticationSession _auth;private readonly IClock _clock;
        private readonly SemaphoreSlim _mutation=new SemaphoreSlim(1,1);private readonly SemaphoreSlim _pump=new SemaphoreSlim(1,1);
        private readonly List<OutboxEntry> _entries=new List<OutboxEntry>();private readonly object _sync=new object();private long _generation;private readonly Random _random=new Random();
        public event Action Changed;
        public QualifierOutbox(OutboxStore store,ScoreManagerApiClient api,AuthenticationSession auth,IClock clock=null) { _store=store;_api=api;_auth=auth;_clock=clock??new SystemClock();_entries.AddRange(store.Load()); }
        public bool HasUnresolved { get { lock(_sync) return _entries.Any(e=>e.State!="sent" || !e.Persisted); } }
        public bool HasCapacity() { return _store.HasCapacity(); }
        public IList<OutboxEntry> Entries { get { lock(_sync) return _entries.Select(e=>StrictJson.Clone(e)).ToArray(); } }
        public IList<OutboxEntry> GetSummaries() {
            lock(_sync) return _entries.Select(e=>new OutboxEntry {Id=e.Id,ChallengeId=e.ChallengeId,OwnerSid=e.OwnerSid,ScoreServerBaseUrl=e.ScoreServerBaseUrl,IdempotencyKey=e.IdempotencyKey,ResultAcceptUntil=e.ResultAcceptUntil,State=e.State,BlockedReason=e.BlockedReason,OwnerMismatch=e.OwnerMismatch,ErrorCode=e.ErrorCode,HttpStatus=e.HttpStatus,RequestId=e.RequestId,Response=e.Response==null?null:StrictJson.Clone(e.Response),RetryCount=e.RetryCount,NextAttemptAt=e.NextAttemptAt,Persisted=e.Persisted,Generation=e.Generation}).ToArray();
        }
        public async Task<OutboxEntry> EnqueueAsync(ChallengeContext context,ResultSnapshot result) {
            if(context.ResultCleared || _store.IsDeleted(result.Metadata.ClientResultId)) return null;
            var entry=new OutboxEntry {Id=result.Metadata.ClientResultId,ChallengeId=context.ChallengeId,OwnerSid=context.OwnerSid,ScoreServerBaseUrl=context.ScoreServerBaseUrl,IdempotencyKey=result.Metadata.ClientResultId,MetadataJson=StrictJson.Serialize(result.Metadata),ReplayGzip=result.ReplayGzip==null?null:(byte[])result.ReplayGzip.Clone(),ResultAcceptUntil=context.ResultAcceptUntil,State="save_failed",Generation=Interlocked.Increment(ref _generation)};
            lock(_sync) { if(_entries.Any(e=>e.ChallengeId==entry.ChallengeId)) return _entries.First(e=>e.ChallengeId==entry.ChallengeId);_entries.Add(entry); } Changed?.Invoke();
            await PersistAsync(entry).ConfigureAwait(false);return entry;
        }
        private bool Exists(OutboxEntry e) { lock(_sync) return _entries.Contains(e); }
        private async Task<bool> PersistAsync(OutboxEntry e) {
            await _mutation.WaitAsync().ConfigureAwait(false);
            try {
                if(!Exists(e)) return false;
                if(_store.IsDeleted(e.Id)) { lock(_sync) _entries.Remove(e);return false; }
                var desired=e.State=="save_failed"?(e.StateAfterSave??"pending"):e.State;
                try { var snapshot=StrictJson.Clone(e);snapshot.State=desired;snapshot.StateAfterSave=null;snapshot.Persisted=true;await Task.Run(()=>_store.Save(snapshot)).ConfigureAwait(false);if(!Exists(e)) return false;e.State=desired;e.StateAfterSave=null;e.Persisted=true;return true; }
                catch { e.StateAfterSave=desired;e.State="save_failed";e.Persisted=false;if(e.ErrorCode==null) e.ErrorCode="outbox_save_failed";return false; }
            } finally { _mutation.Release();Changed?.Invoke(); }
        }
        public async Task RetryAsync(bool explicitRetry=false,CancellationToken token=default(CancellationToken)) {
            if(!await _pump.WaitAsync(0,token).ConfigureAwait(false)) return;
            try {
                OutboxEntry[] entries;lock(_sync) entries=_entries.ToArray();
                foreach(var e in entries) {
                    if(!Exists(e) || e.State=="sent") continue;
                    if(e.ScoreServerBaseUrl!=_auth.Endpoint?.NormalizedUrl) { e.BlockedReason="server_mismatch";Changed?.Invoke();continue; }
                    e.BlockedReason=null;
                    e.OwnerMismatch=e.OwnerSid!=_auth.CurrentSid;
                    if(e.OwnerMismatch) { Changed?.Invoke();continue; }
                    if(e.State=="save_failed" && !await PersistAsync(e).ConfigureAwait(false)) continue;
                    if(e.State=="sent" || e.State=="stopped" || (e.State=="awaiting_auth"&&!explicitRetry)) continue;
                    if(!explicitRetry && e.NextAttemptAt.HasValue && e.NextAttemptAt>_clock.UtcNow) continue;
                    var session=await _auth.EnsureAsync(explicitRetry,token).ConfigureAwait(false);
                    if(session==null) { e.State="awaiting_auth";await PersistAsync(e).ConfigureAwait(false);continue; }
                    if(!CanSend(e,session)) continue;
                    await SendAsync(e,session,token).ConfigureAwait(false);
                }
            } finally { _pump.Release();Changed?.Invoke(); }
        }
        private bool CanSend(OutboxEntry e,ScoreSession s) { return Exists(e) && e.Persisted && e.ScoreServerBaseUrl==_auth.Endpoint?.NormalizedUrl && e.OwnerSid==_auth.CurrentSid && _auth.IsAuthenticated(s) && s.OwnerSid==e.OwnerSid; }
        private async Task SendAsync(OutboxEntry e,ScoreSession session,CancellationToken token) {
            e.State="sending";Changed?.Invoke();bool reauthenticated=false;
            while(CanSend(e,session)) {
                try {
                    var response=await _api.SendResultAsync(session,e.ChallengeId,e.MetadataJson,e.ReplayGzip,e.IdempotencyKey,token).ConfigureAwait(false);
                    if(!Exists(e)) return;
                    e.Response=response;e.ResponseJson=response.RawJson;e.State="sent";e.Persisted=false;e.ErrorCode=null;
                    // First persist successful acceptance, then remove the large payload in a second durable replacement.
                    if(await PersistAsync(e).ConfigureAwait(false)) await TrimSentPayloadAsync(e).ConfigureAwait(false); return;
                } catch(ApiException ex) {
                    if(!Exists(e)) return;
                    e.ErrorCode=ex.Code;e.HttpStatus=ex.HttpStatus;e.RequestId=ex.RequestId;
                    if(ex.HttpStatus==401 || ex.Code=="authentication_required") {
                        e.State="awaiting_auth";
                        if(reauthenticated || e.OwnerSid!=_auth.CurrentSid || e.ScoreServerBaseUrl!=_auth.Endpoint?.NormalizedUrl) break;
                        reauthenticated=true;_auth.Invalidate();session=await _auth.EnsureAsync(true,token).ConfigureAwait(false);
                        if(session==null || !CanSend(e,session)) break;e.State="sending";continue;
                    }
                    if(ex.Code=="result_acceptance_expired" || ex.Code=="challenge_timed_out" || !ex.Retryable) e.State="stopped";
                    else Schedule(e,ex.RetryAfter);break;
                } catch(OperationCanceledException) { if(!Exists(e)) return;Schedule(e,null);e.ErrorCode="network_timeout";break; }
                catch(System.Net.Http.HttpRequestException) { if(!Exists(e)) return;Schedule(e,null);e.ErrorCode="network_unavailable";break; }
                catch(Exception) { if(!Exists(e)) return;e.State="stopped";e.ErrorCode="invalid_response";break; }
            }
            if(Exists(e)) { if(e.State=="sending") e.State="pending";await PersistAsync(e).ConfigureAwait(false); }
        }
        private void Schedule(OutboxEntry e,TimeSpan? retryAfter) { e.State="pending";e.RetryCount++;var delay=retryAfter??TimeSpan.FromSeconds(Math.Min(60,Math.Pow(2,Math.Min(6,e.RetryCount-1)))*(0.8+_random.NextDouble()*0.4));e.NextAttemptAt=_clock.UtcNow+(delay<TimeSpan.Zero?TimeSpan.Zero:delay); }
        private async Task TrimSentPayloadAsync(OutboxEntry e) {
            await _mutation.WaitAsync().ConfigureAwait(false);
            try {
                if(!Exists(e)) return;
                var compact=StrictJson.Clone(e);compact.MetadataJson=null;compact.ReplayGzip=null;
                try { await Task.Run(()=>_store.Save(compact)).ConfigureAwait(false);e.MetadataJson=null;e.ReplayGzip=null; }
                catch { /* Acceptance was already persisted. Keep its payload until later cleanup; never resend a null payload. */ }
            } finally { _mutation.Release(); }
        }
        public async Task ForceClearAsync(System.Collections.Generic.IEnumerable<string> finalizingIds=null) {
            await _mutation.WaitAsync().ConfigureAwait(false);
            try {
                string[] ids;lock(_sync) ids=_entries.Where(e=>e.State!="sent" || !e.Persisted).Select(e=>e.Id).Concat(finalizingIds??new string[0]).Distinct().ToArray();
                await Task.Run(()=>_store.Delete(ids)).ConfigureAwait(false);
                lock(_sync) _entries.RemoveAll(e=>ids.Contains(e.Id));
                Interlocked.Increment(ref _generation);
            } finally { _mutation.Release();Changed?.Invoke(); }
        }
    }
}

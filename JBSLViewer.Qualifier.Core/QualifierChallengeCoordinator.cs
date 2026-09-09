using System;
using System.Threading;
using System.Threading.Tasks;
using System.Collections.Generic;
using System.Linq;
using JBSLViewer.Qualifier.Core.Contracts;
using JBSLViewer.Qualifier.Core.Outbox;
namespace JBSLViewer.Qualifier.Core {
    public sealed class QualifierChallengeCoordinator : IDisposable {
        private readonly ScoreManagerApiClient _api;private readonly AuthenticationSession _auth;private readonly QualifierOutbox _outbox;private readonly IQualifierHost _host;private readonly IClock _clock;
        private readonly QualifierEligibilityEvaluator _evaluator=new QualifierEligibilityEvaluator();private readonly CompletedChallengeGuard _guard=new CompletedChallengeGuard();
        private CancellationTokenSource _statusCancellation;private readonly CancellationTokenSource _lifetime=new CancellationTokenSource();
        private GateToken _statusGate;private StatusResponse _status;private DateTimeOffset _statusAt;private GateToken _confirmation;private ReserveOperation _operation;private int _finalizing;private bool _confirming;private bool _disposed;
        private ScoreSession _statusSession;
        private readonly HashSet<ChallengeContext> _finalizingContexts=new HashSet<ChallengeContext>();
        public string ClientVersion { get; set; } = "JBSLViewer/0.4.0";
        public string GameVersion { get; set; } = "1.37.1";
        public TimeSpan ReserveUiTimeout { get; set; } = TimeSpan.FromSeconds(30);
        public ChallengeContext ActiveChallenge { get; private set; }
        public ReserveOperation PendingReserve { get { return _operation!=null&&!_operation.Resolved?_operation:null; } }
        public bool HasUnresolved { get { return _outbox.HasUnresolved || _finalizing>0 || PendingReserve!=null || ActiveChallenge!=null; } }
        public QualifierViewState ViewState { get; private set; } = new QualifierViewState();
        public event Action StateChanged;
        public QualifierChallengeCoordinator(ScoreManagerApiClient api,AuthenticationSession auth,QualifierOutbox outbox,IQualifierHost host,IClock clock=null) {
            _api=api;_auth=auth;_outbox=outbox;_host=host;_clock=clock??new SystemClock();_host.SelectionChanged+=SelectionChanged;_auth.Changed+=AuthenticationChanged;_outbox.Changed+=OutboxChanged;
        }
        private GateToken Gate(SelectionSnapshot s) { return new GateToken {SelectionGeneration=s.SelectionGeneration,AuthenticationGeneration=_auth.Generation,ScoreServerBaseUrl=_auth.Endpoint?.NormalizedUrl,LeagueId=s.LeagueId,Map=s.Map?.Copy(),CurrentSid=s.CurrentSid,Revision=s.Leaderboard?.Qualifier?.Revision,IsSolo=s.IsSolo}; }
        private bool Current(GateToken gate) { var s=_host.CaptureSelection();return s!=null && gate.Equals(Gate(s)) && s.CurrentSid==_auth.CurrentSid; }
        private void SelectionChanged() { _statusCancellation?.Cancel();_statusGate=null;_status=null; Reevaluate(); }
        private void AuthenticationChanged() { _statusCancellation?.Cancel();_statusGate=null;_status=null;Reevaluate(); }
        private void OutboxChanged() { StateChanged?.Invoke(); }
        public void Reevaluate() {
            if(_disposed) return;
            var s=_host.CaptureSelection();var visible=_evaluator.Evaluate(s,_clock.UtcNow);string[] blockers;
            bool allowed=_host.IsSubmissionAllowed(out blockers);
            if(!visible && _confirmation!=null && !_confirming) CancelConfirmation();
            var matching=_statusGate!=null && Current(_statusGate) && _auth.IsAuthenticated(_statusSession) && _clock.UtcNow-_statusAt<TimeSpan.FromSeconds(10);var status=matching?_status:null;
            if(status!=null && !status.Eligible) visible=false;
            bool can=visible && status!=null && status.Eligible && status.ReasonCode=="eligible" && status.RemainingAttempts>0 && status.Map?.AttemptLimit>0 && status.Cache!=null && !status.Cache.Stale && allowed && !HasUnresolved;
            var message=!visible?null:HasUnresolved?(_outbox.HasUnresolved?"Unresolved result — open settings":ActiveChallenge!=null?"In progress":"Reserving..."):!allowed?"Submission disabled: "+string.Join(", ",blockers??new string[0]):status==null?"Loading remaining attempts...":status.Cache.Stale?"Status cache is stale":status.ReasonCode;
            ViewState=new QualifierViewState {Visible=visible,CanChallenge=can && _confirmation==null && !_confirming,ConfirmationOpen=_confirmation!=null,CanConfirm=can && _confirmation!=null && !_confirming,RemainingAttempts=status?.RemainingAttempts,AttemptLimit=status?.Map?.AttemptLimit,Message=message};StateChanged?.Invoke();
        }
        public async Task RefreshAsync(bool force=false) {
            if(_disposed) return;
            _auth.RefreshIdentity();var s=_host.CaptureSelection();Reevaluate();
            if(!_evaluator.Evaluate(s,_clock.UtcNow) || s.CurrentSid!=_auth.CurrentSid || _auth.Endpoint==null || PendingReserve!=null || ActiveChallenge!=null) return;
            var gate=Gate(s);if(!force && _status!=null && gate.Equals(_statusGate) && _auth.IsAuthenticated(_statusSession) && _clock.UtcNow-_statusAt<TimeSpan.FromSeconds(10)) return;
            _statusCancellation?.Cancel();var cts=CancellationTokenSource.CreateLinkedTokenSource(_lifetime.Token);_statusCancellation=cts;
            try {
                var session=await _auth.EnsureAsync(false,cts.Token);
                if(session==null) { if(Current(gate)) { ViewState.Message="Awaiting authentication — retry in settings";StateChanged?.Invoke(); } return; }
                if(!Current(gate) || !_auth.IsAuthenticated(session)) return;
                var authenticatedStatus=await StatusWithAuthenticationRetryAsync(session,gate,cts.Token);
                if(!Current(gate) || cts.IsCancellationRequested || !_auth.IsAuthenticated(authenticatedStatus.Session)) return;
                var status=authenticatedStatus.Response;ValidateStatus(status,gate);_status=status;_statusSession=authenticatedStatus.Session;_statusGate=gate;_statusAt=_clock.UtcNow;Reevaluate();
            } catch(OperationCanceledException) { }
            catch(Exception ex) { if(Current(gate)) { _status=null;_statusGate=null;Reevaluate();ViewState.Message=ex is ApiException?((ApiException)ex).Code:"Status unavailable";StateChanged?.Invoke(); } }
        }
        private static void ValidateStatus(StatusResponse s,GateToken gate) {
            if(s.Eligible && (s.League==null || s.League.Id!=gate.LeagueId || s.Map==null || !s.Map.Key.Equals(gate.Map) || s.IsParticipant!=true || !s.RemainingAttempts.HasValue || s.Map.AttemptLimit==null)) throw new FormatException("Status does not match selected challenge");
        }
        private sealed class AuthenticatedStatus { public ScoreSession Session;public StatusResponse Response; }
        private async Task<AuthenticatedStatus> StatusWithAuthenticationRetryAsync(ScoreSession session,GateToken gate,CancellationToken token) {
            try { var response=await _api.GetStatusAsync(session,gate,token);return CurrentStatus(session,response); }
            catch(ApiException ex) {
                if(ex.HttpStatus!=401 && ex.Code!="authentication_required") throw;
                if(!Current(gate)) throw;
                _auth.Invalidate();session=await _auth.EnsureAsync(true,token);
                if(session==null || !Current(gate)) throw new ApiException(401,"authentication_required",false);
                try { var response=await _api.GetStatusAsync(session,gate,token);return CurrentStatus(session,response); }
                catch(ApiException retry) { if(retry.HttpStatus==401 || retry.Code=="authentication_required") _auth.AwaitAuthentication();throw; }
            }
        }
        private AuthenticatedStatus CurrentStatus(ScoreSession session,StatusResponse response) {
            // A same-user reauthentication also replaces the CookieContainer. Its identity is
            // finer-grained than the user/endpoint generation, so an old successful status
            // must not be adopted even when every visible gate field is unchanged.
            if(!_auth.IsAuthenticated(session)) throw new OperationCanceledException("Obsolete authentication session");
            return new AuthenticatedStatus {Session=session,Response=response};
        }
        public bool BeginConfirmation() { Reevaluate();if(!ViewState.CanChallenge) return false;_confirmation=Gate(_host.CaptureSelection());_host.SetSelectionLocked(true);Reevaluate();return true; }
        public void CancelConfirmation() { if(_confirming || PendingReserve!=null) return;_confirmation=null;_host.SetSelectionLocked(false);Reevaluate(); }
        public async Task ConfirmAsync() {
            if(_confirming || _confirmation==null || HasUnresolved) return;
            var gate=_confirmation;_confirming=true;Reevaluate();
            try {
                var selection=_host.CaptureSelection();string[] blockers;
                if(!Current(gate) || !_evaluator.Evaluate(selection,_clock.UtcNow) || !_host.IsSubmissionAllowed(out blockers) || !_outbox.HasCapacity()) return;
                var session=await _auth.EnsureAsync(false,_lifetime.Token);
                if(session==null || !Current(gate) || !_auth.IsAuthenticated(session)) return;
                var authenticatedStatus=await StatusWithAuthenticationRetryAsync(session,gate,_lifetime.Token);
                session=authenticatedStatus.Session;var status=authenticatedStatus.Response;
                if(!Current(gate) || !_auth.IsAuthenticated(session)) return;ValidateStatus(status,gate);_status=status;_statusSession=session;_statusGate=gate;_statusAt=_clock.UtcNow;
                selection=_host.CaptureSelection();
                if(!_evaluator.Evaluate(selection,_clock.UtcNow) || status.Cache==null || status.Cache.Stale || !status.Eligible || status.ReasonCode!="eligible" || status.RemainingAttempts<=0 || HasUnresolved || !_host.IsSubmissionAllowed(out blockers) || !_auth.IsAuthenticated(session)) return;
                var key=Guid.NewGuid().ToString();
                var context=new ChallengeContext {LeagueId=gate.LeagueId,OwnerSid=gate.CurrentSid,ScoreServerBaseUrl=gate.ScoreServerBaseUrl,ReserveKey=key,Map=gate.Map.Copy(),ClientVersion=ClientVersion,GameVersion=GameVersion,Timing=new ResultTiming {ConfirmedAtClient=_clock.UtcNow,LocalSongDurationSeconds=selection.LocalSongDurationSeconds,SongSpeedMultiplier=selection.SongSpeedMultiplier}};
                var operation=new ReserveOperation {Gate=gate,Key=key,Session=session,Context=context,Request=new ReserveRequest {LeagueId=gate.LeagueId,Map=gate.Map.Copy(),ClientVersion=ClientVersion,GameVersion=context.GameVersion}};
                _operation=operation;_confirmation=null;
                var resolve=ResolveReserveAsync(operation);
                if(await Task.WhenAny(resolve,Task.Delay(ReserveUiTimeout,_lifetime.Token))!=resolve && !operation.SuccessProcessed && !operation.Resolved) { operation.TimedOut=true;_host.SetSelectionLocked(false);Reevaluate(); }
                // Observe the resolution in this task; callers may keep displaying the unlocked normal menu.
                await resolve;
            } catch(OperationCanceledException) { }
            catch(ApiException ex) { ViewState.Message=ex.Code; }
            catch(Exception) { ViewState.Message="Challenge could not start"; }
            finally { _confirming=false;if(PendingReserve==null) { _confirmation=null;_host.SetSelectionLocked(false); } Reevaluate(); }
        }
        private async Task ResolveReserveAsync(ReserveOperation operation) {
            int retry=0;bool authenticationRetried=false;
            while(!_lifetime.IsCancellationRequested) {
                try {
                    if(retry>0 || operation.TimedOut) {
                        // In-flight completion belongs to the original operation, but new recovery
                        // traffic requires the currently selected identity AND original endpoint.
                        if(operation.Context.OwnerSid!=_auth.CurrentSid || operation.Context.ScoreServerBaseUrl!=_auth.Endpoint?.NormalizedUrl) { await Task.Delay(1000,_lifetime.Token);continue; }
                        var recovered=await _auth.EnsureAsync(false,_lifetime.Token);
                        if(recovered==null) { await Task.Delay(1000,_lifetime.Token);continue; }
                        if(recovered.OwnerSid!=operation.Context.OwnerSid || recovered.Endpoint.NormalizedUrl!=operation.Context.ScoreServerBaseUrl) continue;
                        operation.Session=recovered;
                    }
                    var response=await _api.ReserveAsync(operation.Session,operation.Request,operation.Key,_lifetime.Token);
                    if(operation.SuccessProcessed) return;
                    operation.SuccessProcessed=true;operation.Context.ChallengeId=response.ChallengeId;operation.Context.ResultAcceptUntil=response.ResultAcceptUntil;operation.Context.Timing.ReserveResponseReceivedAtClient=_clock.UtcNow;
                    var context=operation.Context;string failure=null;string[] blockers;
                    if(operation.TimedOut) failure="reserve_response_after_timeout";
                    else if(operation.Gate.CurrentSid!=_auth.CurrentSid || operation.Gate.AuthenticationGeneration!=_auth.Generation) failure="identity_changed";
                    if(!operation.TimedOut && operation.Gate.ScoreServerBaseUrl!=_auth.Endpoint?.NormalizedUrl) failure="score_server_changed";
                    if(failure==null && (!Current(operation.Gate) || !response.Map.Equals(operation.Request.Map))) failure="selection_changed";
                    if(failure==null && !_evaluator.Evaluate(_host.CaptureSelection(),_clock.UtcNow)) failure="start_gate_changed";
                    if(failure==null && (!_auth.IsAuthenticated(operation.Session) || !_host.IsSubmissionAllowed(out blockers))) failure="submission_disabled";
                    operation.Resolved=true;
                    if(failure!=null) { await RejectBeforePlayAsync(context,failure);return; }
                    ActiveChallenge=context;context.PlayInvoked=true;
                    _host.IsSubmissionAllowed(out blockers);context.Submission.Observe(true,blockers);
                    bool started=false;try { started=await _host.StartStandardPlayAsync(context); } catch { }
                    _host.SetSelectionLocked(false);
                    if(!started && !context.Detached && !context.Completed) await RejectBeforePlayAsync(context,"standard_play_invocation_failed");
                    Reevaluate();return;
                } catch(ApiException ex) {
                    if(ex.HttpStatus==401 || ex.Code=="authentication_required") {
                        operation.TimedOut=true;_host.SetSelectionLocked(false);_auth.Invalidate();
                        if(!authenticationRetried && operation.Context.OwnerSid==_auth.CurrentSid && operation.Context.ScoreServerBaseUrl==_auth.Endpoint?.NormalizedUrl) { authenticationRetried=true;await _auth.EnsureAsync(true,_lifetime.Token); }
                        else _auth.AwaitAuthentication();
                    }
                    else if(!ex.Retryable) { operation.Resolved=true;_host.SetSelectionLocked(false);throw; }
                } catch(OperationCanceledException) { if(_lifetime.IsCancellationRequested) return; }
                catch(System.Net.Http.HttpRequestException) { }
                catch { operation.Resolved=true;_host.SetSelectionLocked(false);throw; }
                operation.TimedOut=true;_host.SetSelectionLocked(false);Reevaluate();
                // An unknown reserve is process-local and always retried with the original key and body.
                await Task.Delay(TimeSpan.FromSeconds(Math.Min(60,Math.Pow(2,Math.Min(retry++,6)))),_lifetime.Token);
            }
        }
        private async Task RejectBeforePlayAsync(ChallengeContext context,string code) {
            DetachForFinalization(context,context.GameplayGeneration);
            var observed=new ResultMetadata {GameVersion=context.GameVersion,Diagnostics=new ResultDiagnostics {FailureCode=code}};
            await CompleteAsync(context,QualifierResultFactory.Create(context,"preflight_rejected",observed,null,_clock));
        }
        public bool DetachForFinalization(ChallengeContext context,long gameplayGeneration) {
            if(context==null || context.Detached || context.Completed || !_guard.TryComplete(context.ChallengeId,gameplayGeneration)) return false;
            context.Detached=true;context.Finalizing=true;context.GameplayGeneration=gameplayGeneration;_finalizing++;_finalizingContexts.Add(context);
            context.FrozenSubmission=context.Submission.ToContract();context.FrozenTiming=StrictJson.Clone(context.Timing);
            if(ReferenceEquals(ActiveChallenge,context)) ActiveChallenge=null;
            StateChanged?.Invoke();return true;
        }
        public async Task CompleteAsync(ChallengeContext context,ResultSnapshot result) {
            if(context==null || context.Completed || context.ResultCleared) return;
            if(!context.Detached) DetachForFinalization(context,context.GameplayGeneration);
            context.Completed=true;
            try { await _outbox.EnqueueAsync(context,result); }
            finally { if(context.Finalizing) { context.Finalizing=false;_finalizing--;_finalizingContexts.Remove(context); } StateChanged?.Invoke(); }
            await _outbox.RetryAsync(false,_lifetime.Token);
        }
        public async Task ForceClearResultsAsync() {
            var contexts=_finalizingContexts.ToArray();
            await _outbox.ForceClearAsync(contexts.Select(c=>c.ClientResultId));
            foreach(var context in contexts) { context.ResultCleared=true;if(context.Finalizing) {context.Finalizing=false;_finalizing--;_finalizingContexts.Remove(context);} }
            _status=null;_statusGate=null;Reevaluate();await RefreshAsync(true);
        }
        public async Task MarkStartedAsync(ChallengeContext context,long gameplayGeneration) {
            if(context==null || context.Detached || context.Completed || !ReferenceEquals(context,ActiveChallenge) || context.Started) return;
            context.GameplayGeneration=gameplayGeneration;context.Started=true;if(!context.Timing.StartedAtClient.HasValue) context.Timing.StartedAtClient=_clock.UtcNow;
            string[] blockers;var allowed=_host.IsSubmissionAllowed(out blockers);if(!context.Submission.StartObserved) context.Submission.MarkStarted(allowed,blockers);allowed=context.Submission.ToContract().AllowedAtStart;
            if(!allowed) return;
            if(context.OwnerSid!=_auth.CurrentSid || context.ScoreServerBaseUrl!=_auth.Endpoint?.NormalizedUrl) return;
            var session=await _auth.EnsureAsync(false,_lifetime.Token);if(session==null || !_auth.IsAuthenticated(session) || session.OwnerSid!=context.OwnerSid || session.Endpoint.NormalizedUrl!=context.ScoreServerBaseUrl) return;
            try { await _api.StartedAsync(session,context.ChallengeId,new StartedRequest {ActualMap=context.Map.Copy(),SubmissionAllowed=true,StartedAtClient=context.Timing.StartedAtClient.Value},_lifetime.Token); } catch { /* Missing started must not cancel actual gameplay or its result. */ }
        }
        public void Dispose() { _disposed=true;_lifetime.Cancel();_statusCancellation?.Cancel();_host.SelectionChanged-=SelectionChanged;_auth.Changed-=AuthenticationChanged;_outbox.Changed-=OutboxChanged; }
    }
}

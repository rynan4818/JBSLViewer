using System;
using System.Linq;
using System.Threading.Tasks;
using JBSLViewer.Qualifier.Core;
using JBSLViewer.Qualifier.Core.Contracts;
using JBSLViewer.Qualifier.Core.Outbox;
namespace JBSLViewer.Qualifier.Tests {
    internal static class AdditionalScenarios {
        public static async Task Run() {
            using(var r=new Rig()) {
                await r.Coordinator.RefreshAsync();r.Coordinator.BeginConfirmation();var completion=new TaskCompletionSource<StatusResponse>();GateToken captured=null;r.Api.Status=(s,g)=>{captured=g;return completion.Task;};var confirming=r.Coordinator.ConfirmAsync();await Task.Delay(20);await r.Auth.EnsureAsync(true);completion.SetResult(r.Api.StatusSuccess(captured));await confirming;Program.Check(r.Api.ReserveCalls==0 && r.Host.Plays==0 && !r.Host.Locked,"Confirm cannot reserve with a status from a same-sid retired session");
            }
            using(var r=new Rig()) {
                var completion=new TaskCompletionSource<StatusResponse>();GateToken gate=null;ScoreSession oldSession=null;r.Api.Status=(s,g)=>{oldSession=s;gate=g;return completion.Task;};var refresh=r.Coordinator.RefreshAsync();await Task.Delay(20);
                var replacement=await r.Auth.EnsureAsync(true);Program.Check(replacement!=null && !ReferenceEquals(replacement,oldSession),"same-sid reauthentication replaces session identity");completion.SetResult(r.Api.StatusSuccess(gate));await refresh;r.Coordinator.Reevaluate();Program.Check(!r.Coordinator.ViewState.CanChallenge && r.Coordinator.ViewState.RemainingAttempts==null,"late status from same-sid retired session is discarded");
                r.Api.Status=null;await r.Coordinator.RefreshAsync();Program.Check(r.Coordinator.ViewState.CanChallenge,"current-session status refresh recovers without stale cache TTL wait");await r.Auth.EnsureAsync(true);r.Coordinator.Reevaluate();Program.Check(!r.Coordinator.ViewState.CanChallenge && !r.Coordinator.BeginConfirmation(),"same-sid reauthentication invalidates already displayed status cache");
            }
            using(var r=new Rig()) {
                var original=await r.Auth.EnsureAsync();original.Cookies.SetCookies(original.Endpoint.Uri,"jbslq_session=A; Path=/");r.Auth.Configure("http://127.0.0.1:18082/",true);var port=await r.Auth.EnsureAsync();Program.Check(port.Cookies.Count==0 && !ReferenceEquals(original.Cookies,port.Cookies),"same-host different-port uses separate CookieContainer");
                r.Auth.Configure("http://127.0.0.1:18082/Other/",true);var path=await r.Auth.EnsureAsync();original.Cookies.SetCookies(original.Endpoint.Uri,"jbslq_session=late-A; Path=/");Program.Check(path.Cookies.Count==0 && !ReferenceEquals(path.Cookies,port.Cookies),"different base path and late retired Set-Cookie cannot affect current cookies");
                r.Identity.CurrentSid="new-user";r.Auth.RefreshIdentity();var identity=await r.Auth.EnsureAsync();Program.Check(identity.OwnerSid=="new-user" && identity.Cookies.Count==0 && !ReferenceEquals(identity.Cookies,path.Cookies),"new identity has a fresh generation CookieContainer");
            }
            using(var r=new Rig()) {
                var gameplay=new TaskCompletionSource<bool>();r.Host.Play=c=>gameplay.Task;r.Coordinator.ReserveUiTimeout=TimeSpan.FromMilliseconds(20);await r.Coordinator.RefreshAsync();r.Coordinator.BeginConfirmation();var confirm=r.Coordinator.ConfirmAsync();await Task.Delay(70);Program.Check(r.Host.Locked && r.Coordinator.ActiveChallenge!=null && !r.Coordinator.ActiveChallenge.Detached,"360 confirmation/load is not given a reserve UI timeout");gameplay.SetResult(true);await confirm;Program.Check(r.Host.Plays==1 && r.Api.ResultCalls==0,"long load still reaches one normal challenge Play");
            }
            using(var r=new Rig()) {
                var c=r.Context();r.Coordinator.DetachForFinalization(c,1);await r.Coordinator.ForceClearResultsAsync();var result=QualifierResultFactory.Create(c,"restart",null,null,r.Clock);await r.Coordinator.CompleteAsync(c,result);Program.Check(r.Outbox.Entries.Count==0 && r.Api.ResultCalls==0 && !r.Coordinator.HasUnresolved,"force clear during deferred gzip blocks late completion");
                Program.Check(new OutboxStore(r.Store.DirectoryPath).IsDeleted(c.ClientResultId),"deferred result tombstone durable before encoder finishes");
            }
            using(var r=new Rig()) {
                var count=0;r.Api.Status=(s,g)=>{if(count++==0) throw new ApiException(401,"authentication_required",false);return Task.FromResult(r.Api.StatusSuccess(g));};await r.Coordinator.RefreshAsync();Program.Check(r.Api.AuthCalls==2 && r.Coordinator.ViewState.CanChallenge,"status 401 reauth once after server session reset");
                r.Api.Status=(s,g)=>{throw new ApiException(401,"authentication_required",false);};await r.Coordinator.RefreshAsync(true);var calls=r.Api.AuthCalls;await r.Coordinator.RefreshAsync(true);Program.Check(r.Api.AuthCalls==calls && !r.Coordinator.ViewState.CanChallenge,"second status 401 requires explicit authentication retry");
            }
            using(var r=new Rig()) {
                var result=new TaskCompletionSource<StatusResponse>();GateToken captured=null;r.Api.Status=(s,g)=>{captured=g;return result.Task;};var refresh=r.Coordinator.RefreshAsync();await Task.Delay(20);r.Host.Selection.Map=MapKey.Create(r.Host.Selection.Map.Hash,"Standard","Hard");r.Host.Change();result.SetResult(r.Api.StatusSuccess(captured));await refresh;Program.Check(!r.Coordinator.ViewState.Visible && !r.Coordinator.ViewState.CanChallenge,"old selection status cannot enable new map");
            }
            using(var r=new Rig()) {
                await r.Coordinator.RefreshAsync();r.Coordinator.BeginConfirmation();r.Clock.UtcNow=r.Host.Selection.Leaderboard.End;await r.Coordinator.ConfirmAsync();Program.Check(!r.Host.Locked && r.Api.ReserveCalls==0 && !r.Coordinator.ViewState.Visible,"dialog deadline crossing consumes no attempt");
            }
            using(var r=new Rig()) {
                await r.Coordinator.RefreshAsync();r.Coordinator.BeginConfirmation();r.Coordinator.CancelConfirmation();await r.Coordinator.ConfirmAsync();Program.Check(r.Api.ReserveCalls==0 && !r.Host.Locked,"cancel before confirm consumes nothing");
            }
            foreach(var change in new[]{"owner","endpoint","deadline","map-response"}) {
                using(var r=new Rig()) {
                    var result=new TaskCompletionSource<ReserveResponse>();r.Api.Reserve=(s,q,k)=>result.Task;await r.Coordinator.RefreshAsync();r.Coordinator.BeginConfirmation();var confirming=r.Coordinator.ConfirmAsync();await Task.Delay(10);var op=r.Coordinator.PendingReserve;var response=r.Api.Success(op.Request);
                    if(change=="owner") { r.Identity.CurrentSid="other";r.Auth.RefreshIdentity(); }
                    if(change=="endpoint") r.Auth.Configure("http://localhost:18081/",true);
                    if(change=="deadline") r.Clock.UtcNow=r.Host.Selection.Leaderboard.End;
                    if(change=="map-response") response.Map=MapKey.Create(op.Request.Map.Hash,"Standard","Hard");
                    string payload=null;r.Api.Result=(s,id,m,b,k)=>{payload=m;return Task.FromResult(new ResultResponse {ChallengeId=id,Status="submitted"});};result.SetResult(response);await confirming;
                    Program.Check(r.Host.Plays==0,"reserve changed "+change+" cannot Play");
                    if(change=="owner" || change=="endpoint") { var e=r.Outbox.Entries.Single();payload=e.MetadataJson;Program.Check(e.OwnerSid==op.Context.OwnerSid && e.ScoreServerBaseUrl==op.Gate.ScoreServerBaseUrl,"reserve changed "+change+" result retains original ownership/endpoint"); }
                    Program.Check((string)StrictJson.Object(payload)["map"]["difficulty"]=="ExpertPlus","reserve "+change+" result retains requested MapKey");
                }
            }
            using(var r=new Rig()) {
                r.Host.Play=c=>Task.FromResult(false);await r.Coordinator.RefreshAsync();r.Coordinator.BeginConfirmation();await r.Coordinator.ConfirmAsync();Program.Check(r.Host.Plays==1 && r.Api.ResultCalls==1 && r.Coordinator.ActiveChallenge==null,"explicit standard Play failure saved once");
            }
            using(var r=new Rig()) {
                var c=r.Context();c.GameplayGeneration=4;c.Submission.MarkStarted(false,"blocked");var observed=new ResultMetadata {Timing=new ResultTiming {StartedAtClient=r.Clock.UtcNow},ScoreValidity=new ScoreValidity {PlayInstanceCount=1}};
                var failed=QualifierResultFactory.Create(c,"preflight_rejected",observed,null,r.Clock);Program.Check(failed.Metadata.ScoreValidity.PlayInstanceCount==1 && failed.Metadata.Timing.StartedAtClient.HasValue,"Gameplay preflight failure preserves actual play count and time");
                foreach(var end in new[]{"quit","restart","unknown","preflight_rejected","clear","fail"}) {
                    var m=QualifierResultFactory.Create(c,end,null,null,r.Clock).Metadata;var expected=end=="clear"||end=="fail"?"submission_disabled":end=="restart"?"restarted":end;Program.Check(m.ScoreValidity.InvalidReason==expected && !m.ScoreValidity.ValidForRanking,"combined blockers priority "+end);
                }
                var pending=new QualifierOutbox(new OutboxStore(r.Store.DirectoryPath),r.Api,r.Auth,r.Clock);await pending.EnqueueAsync(c,failed);string original=pending.Entries.Single().MetadataJson;r.Clock.UtcNow=r.Clock.UtcNow.AddDays(365);r.Api.Result=(s,id,m,b,k)=>{Program.Check(m==original,"timing unchanged beyond local result deadline");throw new ApiException(503,"retry",true);};await pending.RetryAsync(true);Program.Check(pending.Entries.Single().State=="pending","client does not locally discard expired result");
                r.Auth.ClearConfiguration();await pending.RetryAsync(true);Program.Check(pending.GetSummaries().Single().BlockedReason=="server_mismatch" && r.Auth.Endpoint==null,"cleared endpoint blocks old Cookie and outbox send");
            }
        }
    }
}

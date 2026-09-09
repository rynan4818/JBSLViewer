using System;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using JBSLViewer.Qualifier.Core;
using JBSLViewer.Qualifier.Core.Contracts;
namespace JBSLViewer.Qualifier.Tests {
    internal static class CoreScenarios {
        public static async Task Run() {
            ResultGameVersions();
            using(var r=new Rig()) {
                var e=new QualifierEligibilityEvaluator();var s=r.Host.Selection;Program.Check(e.Evaluate(s,r.Clock.UtcNow),"eligible local gate");
                var end=s.Leaderboard.End;r.Clock.UtcNow=end.AddSeconds(-180);Program.Check(e.Evaluate(s,r.Clock.UtcNow),"start deadline equality allowed");r.Clock.UtcNow=r.Clock.UtcNow.AddTicks(1);Program.Check(!e.Evaluate(s,r.Clock.UtcNow),"start deadline after equality rejected");r.Clock.UtcNow=end.AddMinutes(-10);
                s.LocalSongDurationSeconds=null;Program.Check(!e.Evaluate(s,r.Clock.UtcNow),"unknown local duration hides qualifier");s.LocalSongDurationSeconds=180;
                var json=StrictJson.Serialize(s.Leaderboard);Program.Check(StrictJson.ParseLeaderboard(json).LeagueId==3023,"strict leaderboard valid");Program.Reject(()=>StrictJson.ParseLeaderboard(json.Replace("\"league_id\":3023","\"league_id\":\"3023\"")),"string league ID rejected");Program.Reject(()=>StrictJson.ParseLeaderboard(json.Replace("\"league_id\":3023","\"league_id\":3023.0")),"fractional JSON league ID rejected");
                foreach(var mode in new[]{"non-solo","non-participant","wrong-method","wrong-map","stale"}) {
                    s.IsSolo=mode!="non-solo";s.CurrentSid=mode=="non-participant"?"other":r.Identity.CurrentSid;s.Leaderboard.Qualifier.SubmissionMethod=mode=="wrong-method"?"external_leaderboard":"jbsl_qualifier_v1";s.Map.Difficulty=mode=="wrong-map"?"Hard":"ExpertPlus";s.LeaderboardFresh=mode!="stale";await r.Coordinator.RefreshAsync(true);
                    Program.Check(r.Api.AuthCalls==0 && r.Api.StatusCalls==0 && r.Api.ReserveCalls==0,"zero score communication: "+mode);
                }
            }
            Program.Reject(()=>ScoreServerEndpoint.Parse("http://example.com",true),"remote HTTP forbidden");Program.Reject(()=>ScoreServerEndpoint.Parse("http://localhost",false),"development opt-in required");Program.Reject(()=>ScoreServerEndpoint.Parse("https://a.test/?q=x",false),"query in server URL forbidden");
            Program.Reject(()=>StrictJson.Object("{\"schemaVersion\":1,\"schemaVersion\":2}"),"duplicate JSON property rejected");Program.Reject(()=>StrictJson.Object("{\"x\":NaN}"),"non-finite JSON number rejected");
            Program.Check(ScoreServerEndpoint.Parse("HTTPS://EXAMPLE.COM/Base///",false).NormalizedUrl=="https://example.com:443/Base/","endpoint canonical port/path");
            var h=new SubmissionHistory();h.Observe(false,"x");h.Observe(true);h.MarkStarted(true);Program.Check(!h.ToContract().RemainedAllowed,"load-time blocker remains latched");var next=new SubmissionHistory();next.MarkStarted(true);Program.Check(next.ToContract().RemainedAllowed,"next play has fresh history");
            using(var r=new Rig()) {
                await Task.WhenAll(Enumerable.Range(0,20).Select(i=>r.Auth.EnsureAsync()));Program.Check(r.Api.AuthCalls==1,"single flight auth");
                await r.Coordinator.RefreshAsync();Program.Check(r.Coordinator.BeginConfirmation(),"confirmation opens after status");await r.Coordinator.ConfirmAsync();Program.Check(r.Api.ReserveCalls==1 && r.Host.Plays==1,"one reserve and one standard Play");await r.Coordinator.ConfirmAsync();Program.Check(r.Host.Plays==1,"double confirm cannot play twice");
                var c=r.Coordinator.ActiveChallenge;await r.Coordinator.MarkStartedAsync(c,1);Program.Check(r.Coordinator.DetachForFinalization(c,1) && r.Coordinator.ActiveChallenge==null && r.Coordinator.HasUnresolved,"synchronous detach retains unresolved result");Program.Check(!r.Coordinator.DetachForFinalization(c,1),"duplicate finish ignored");
                var snapshot=QualifierResultFactory.Create(c,"clear",new ResultMetadata(),null,r.Clock);Program.Check(snapshot.Metadata.EndType=="clear" && snapshot.Metadata.ScoreValidity.InvalidReason=="replay_unavailable","clear replay failure saved as invalid clear");await r.Coordinator.CompleteAsync(c,snapshot);Program.Check(r.Api.ResultCalls==1,"detached result persisted then sent");
            }
            using(var r=new Rig()) {
                var completion=new TaskCompletionSource<ReserveResponse>();r.Api.Reserve=(s,q,k)=>completion.Task;r.Coordinator.ReserveUiTimeout=TimeSpan.FromMilliseconds(20);
                await r.Coordinator.RefreshAsync();r.Coordinator.BeginConfirmation();var confirm=r.Coordinator.ConfirmAsync();await Task.Delay(60);Program.Check(!r.Host.Locked && r.Host.Plays==0 && r.Coordinator.PendingReserve!=null,"HTTP timeout unlocks normal play while reserve remains unresolved");
                r.Api.Result=(s,c,m,b,k)=>{var data=StrictJson.Object(m);Program.Check((string)data["diagnostics"]["failureCode"]=="reserve_response_after_timeout" && b==null,"late success metadata-only failure");return Task.FromResult(new ResultResponse {ChallengeId=c,Status="submitted"});};
                completion.SetResult(r.Api.Success(r.Coordinator.PendingReserve.Request));await confirm;Program.Check(r.Host.Plays==0 && r.Api.ResultCalls==1,"late reserve never restores or auto-plays");
            }
            using(var r=new Rig()) {
                var pending=new TaskCompletionSource<AuthResponse>();r.Api.Auth=s=>pending.Task;var old=r.Auth.EnsureAsync();await Task.Delay(20);r.Identity.CurrentSid="B";r.Auth.RefreshIdentity();pending.SetResult(new AuthResponse {Authenticated=true,User=new AuthUser {Sid="76561198000000000"},ExpiresAt=r.Clock.UtcNow.AddHours(1)});Program.Check(await old==null,"old auth generation discarded");
                r.Api.Auth=s=>Task.FromResult(new AuthResponse {Authenticated=true,User=new AuthUser {Sid="wrong"},ExpiresAt=r.Clock.UtcNow.AddHours(1)});Program.Check(await r.Auth.EnsureAsync()==null,"sid mismatch rejected");var count=r.Api.AuthCalls;await r.Auth.EnsureAsync();Program.Check(r.Api.AuthCalls==count,"failed auth does not loop automatically");
            }
        }
        private static void ResultGameVersions() {
            using(var r=new Rig()) {
                var context=r.Context();
                foreach(var endType in new[]{"clear","fail"}) {
                    foreach(var version in new[]{"1.29.1","1.29.1_4575554838","1.29.1_1234567890"}) {
                        var observed=new ResultMetadata {GameVersion=version};
                        var result=QualifierResultFactory.Create(context,endType,observed,null,r.Clock);
                        var json=StrictJson.Object(StrictJson.Serialize(result.Metadata));
                        Program.Check((string)json["gameVersion"]==version,"result JSON preserves observed game version: "+endType+" / "+version);
                    }
                }
                foreach(var version in new string[]{null,""," \t "}) {
                    var result=QualifierResultFactory.Create(context,"preflight_rejected",new ResultMetadata {GameVersion=version},null,r.Clock);
                    var json=StrictJson.Object(StrictJson.Serialize(result.Metadata));
                    Program.Check((string)json["gameVersion"]=="1.29.1" && result.Metadata.ScoreValidity.InvalidReason=="preflight_rejected","preflight result supplies default for missing or blank game version");
                }
                var unobserved=QualifierResultFactory.Create(context,"preflight_rejected",null,null,r.Clock);
                Program.Check(unobserved.Metadata.GameVersion=="1.29.1" && unobserved.Metadata.ScoreValidity.PlayInstanceCount==0,"unobserved preflight result retains default game version");
            }
        }
    }
}

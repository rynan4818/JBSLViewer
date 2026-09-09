using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using JBSLViewer.Qualifier.Core;
using JBSLViewer.Qualifier.Core.Contracts;
using JBSLViewer.Qualifier.Core.Outbox;
namespace JBSLViewer.Qualifier.Tests {
    internal sealed class TestClock : IClock { public DateTimeOffset UtcNow { get; set; } = new DateTimeOffset(2030,1,1,0,0,0,TimeSpan.Zero); }
    internal sealed class TicketProvider : IPlatformTicketProvider { public string CurrentSid { get; set; }="76561198000000000";public int Calls;public Task<PlatformTicket> GetTicketAsync(CancellationToken token) { Calls++;return Task.FromResult(new PlatformTicket {Provider="steamTicket",Ticket="mock-ticket"}); } }
    internal sealed class Host : IQualifierHost {
        public SelectionSnapshot Selection;public bool Allowed=true;public bool Locked;public int Plays;public Func<ChallengeContext,Task<bool>> Play;
        public event Action SelectionChanged;
        public SelectionSnapshot CaptureSelection() { return Selection; }
        public bool IsSubmissionAllowed(out string[] blockers) { blockers=Allowed?new string[0]:new[]{"test-disabled"};return Allowed; }
        public void SetSelectionLocked(bool value) { Locked=value; }
        public Task<bool> StartStandardPlayAsync(ChallengeContext c) { Plays++;return Play!=null?Play(c):Task.FromResult(true); }
        public void Change() { Selection.SelectionGeneration++;SelectionChanged?.Invoke(); }
    }
    internal sealed class TestApi : ScoreManagerApiClient {
        public int AuthCalls,StatusCalls,ReserveCalls,ResultCalls;public TestClock Clock;public Func<ScoreSession,Task<AuthResponse>> Auth;
        public Func<ScoreSession,ReserveRequest,string,Task<ReserveResponse>> Reserve;public Func<ScoreSession,string,string,byte[],string,Task<ResultResponse>> Result;public Func<ScoreSession,GateToken,Task<StatusResponse>> Status;
        public override Task<AuthResponse> AuthenticateAsync(ScoreSession s,PlatformTicket t,CancellationToken token) { AuthCalls++;return Auth!=null?Auth(s):Task.FromResult(new AuthResponse {SchemaVersion=1,Authenticated=true,User=new AuthUser {Sid=s.OwnerSid},ExpiresAt=Clock.UtcNow.AddHours(1)}); }
        public override Task<StatusResponse> GetStatusAsync(ScoreSession s,GateToken g,CancellationToken token) { StatusCalls++;return Status!=null?Status(s,g):Task.FromResult(StatusSuccess(g)); }
        public StatusResponse StatusSuccess(GateToken g) { return new StatusResponse {SchemaVersion=1,Eligible=true,ReasonCode="eligible",IsParticipant=true,RemainingAttempts=3,League=new StatusLeague {Id=g.LeagueId},Map=new StatusMap {Hash=g.Map.Hash,Characteristic=g.Map.Characteristic,Difficulty=g.Map.Difficulty,AttemptLimit=3},Cache=new StatusCache {FetchedAt=Clock.UtcNow}}; }
        public override Task<ReserveResponse> ReserveAsync(ScoreSession s,ReserveRequest r,string key,CancellationToken token) { ReserveCalls++;return Reserve!=null?Reserve(s,r,key):Task.FromResult(Success(r)); }
        public ReserveResponse Success(ReserveRequest r) { return new ReserveResponse {SchemaVersion=1,ChallengeId=Guid.NewGuid().ToString(),Map=r.Map,Status="reserved",AttemptLimit=3,AttemptNumber=1,RemainingAttempts=2,ReservedAt=Clock.UtcNow,ResultAcceptUntil=Clock.UtcNow.AddDays(1)}; }
        public override Task<ResultResponse> SendResultAsync(ScoreSession s,string c,string m,byte[] b,string k,CancellationToken token) { ResultCalls++;return Result!=null?Result(s,c,m,b,k):Task.FromResult(new ResultResponse {SchemaVersion=1,ChallengeId=c,Status="submitted",SubmissionId=Guid.NewGuid().ToString(),ReceivedAt=Clock.UtcNow}); }
        public override Task StartedAsync(ScoreSession s,string c,StartedRequest r,CancellationToken token) { return Task.FromResult(0); }
    }
    internal sealed class Rig : IDisposable {
        public TestClock Clock=new TestClock();public TicketProvider Identity=new TicketProvider();public TestApi Api;public AuthenticationSession Auth;public Host Host;public OutboxStore Store;public QualifierOutbox Outbox;public QualifierChallengeCoordinator Coordinator;
        public Rig() { Api=new TestApi {Clock=Clock};Auth=new AuthenticationSession(Api,Identity,Clock);Auth.Configure("http://127.0.0.1:18081",true);Host=new Host {Selection=Selection(Clock.UtcNow,Identity.CurrentSid)};Store=new OutboxStore(Path.Combine(Path.GetTempPath(),"jbsl-core-test-"+Guid.NewGuid()));Outbox=new QualifierOutbox(Store,Api,Auth,Clock);Coordinator=new QualifierChallengeCoordinator(Api,Auth,Outbox,Host,Clock); }
        public static SelectionSnapshot Selection(DateTimeOffset now,string sid) {
            var map=MapKey.Create("0123456789ABCDEF0123456789ABCDEF01234567","Standard","ExpertPlus");
            var board=new LeaderboardContract {LeagueId=3023,Title="Test",IsLive=true,IsOpen=true,End=now.AddHours(1),Participants=new System.Collections.Generic.List<Participant>{new Participant {Sid=sid}},Qualifier=new QualifierSettings {Enabled=true,SubmissionMethod="jbsl_qualifier_v1",Revision="1"},Maps=new System.Collections.Generic.List<QualifierMap>{new QualifierMap {Hash=map.Hash,Characteristic=map.Characteristic,Difficulty=map.Difficulty,AttemptLimit=3,Title="Test"}}};
            return new SelectionSnapshot {CurrentSid=sid,IsSolo=true,LeagueId=3023,Map=map,Leaderboard=board,LeaderboardFresh=true,LocalSongDurationSeconds=180,SongSpeedMultiplier=1};
        }
        public ChallengeContext Context() { return new ChallengeContext {ChallengeId=Guid.NewGuid().ToString(),OwnerSid=Identity.CurrentSid,ScoreServerBaseUrl=Auth.Endpoint.NormalizedUrl,Map=Host.Selection.Map.Copy(),ResultAcceptUntil=Clock.UtcNow.AddHours(2),ClientVersion="JBSLViewer/test"}; }
        public void Dispose() { Coordinator.Dispose();Auth.Dispose(); }
    }
}

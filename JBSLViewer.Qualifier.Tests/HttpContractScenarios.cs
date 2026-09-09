using System;
using System.IO;
using System.Net.Http;
using System.Net;
using System.Linq;
using System.IO.Compression;
using System.Threading;
using System.Threading.Tasks;
using JBSLViewer.Qualifier.Core;
using JBSLViewer.Qualifier.Core.Contracts;
using JBSLViewer.Qualifier.Core.Outbox;
using JBSLViewer.Qualifier.Core.Replay;
namespace JBSLViewer.Qualifier.Tests {
    internal static class HttpContractScenarios {
        public static async Task Run(string score,string web) {
            var identity=new TicketProvider();var clock=new SystemClock();var api=new ScoreManagerApiClient();
            using(var auth=new AuthenticationSession(api,identity,clock)) {
                auth.Configure(score,true);var session=await auth.EnsureAsync();Program.Check(session!=null,"real HTTP ticket authentication");var me=await api.GetMeAsync(session,CancellationToken.None);Program.Check(me.User.Sid==identity.CurrentSid && session.Cookies.Count>0,"real CookieContainer session -> me");
                LeaderboardContract board;using(var http=new HttpClient(new HttpClientHandler {UseProxy=false})) board=StrictJson.ParseLeaderboard(await http.GetStringAsync(web.TrimEnd('/')+"/leaderboard/api/3023"));Program.Check(board.LeagueId==3023,"real WEB relay strict leaderboard");
                var gate=new GateToken {LeagueId=3023,Map=board.Maps[0].Key,CurrentSid=identity.CurrentSid,Revision=board.Qualifier.Revision};var status=await api.GetStatusAsync(session,gate,CancellationToken.None);Program.Check(status.Eligible && !status.Cache.Stale && status.RemainingAttempts>0,"real status eligible with attempts");
                var request=new ReserveRequest {LeagueId=3023,Map=gate.Map,ClientVersion="JBSLViewer/integration"};var key=Guid.NewGuid().ToString();var reserve=await api.ReserveAsync(session,request,key,CancellationToken.None);var duplicate=await api.ReserveAsync(session,request,key,CancellationToken.None);Program.Check(reserve.RawJson==duplicate.RawJson,"real reserve duplicate raw response snapshot");
                await api.StartedAsync(session,reserve.ChallengeId,new StartedRequest {ActualMap=gate.Map,SubmissionAllowed=true,StartedAtClient=clock.UtcNow},CancellationToken.None);Program.Check(true,"real started notification");
                var context=new ChallengeContext {ChallengeId=reserve.ChallengeId,OwnerSid=identity.CurrentSid,ScoreServerBaseUrl=auth.Endpoint.NormalizedUrl,Map=gate.Map,ClientVersion="JBSLViewer/integration",ResultAcceptUntil=reserve.ResultAcceptUntil};var snapshot=QualifierResultFactory.Create(context,"preflight_rejected",new ResultMetadata {Diagnostics=new ResultDiagnostics {FailureCode="integration_probe"}},null,clock);
                var store=new OutboxStore(Path.Combine(Path.GetTempPath(),"jbsl-http-probe-"+Guid.NewGuid()));var outbox=new QualifierOutbox(store,api,auth,clock);var e=await outbox.EnqueueAsync(context,snapshot);var metadata=e.MetadataJson;var resultKey=e.IdempotencyKey;await outbox.RetryAsync(true);Program.Check(!outbox.HasUnresolved && outbox.Entries[0].Response!=null,"real durable metadata-only result accepted");var accepted=await api.SendResultAsync(await auth.EnsureAsync(),context.ChallengeId,metadata,null,resultKey,CancellationToken.None);Program.Check(accepted.RawJson==outbox.Entries[0].ResponseJson,"real result duplicate raw response snapshot");
                session=await auth.EnsureAsync();var clearReserve=await api.ReserveAsync(session,request,Guid.NewGuid().ToString(),CancellationToken.None);await SendReplayResult(api,auth,clock,identity,clearReserve,"clear");
                // Separate sessions share the same authenticated cookie context; requests use the exact production client.
                ServicePointManager.FindServicePoint(session.Endpoint.Uri).ConnectionLimit=128;
                var concurrentKey=Guid.NewGuid().ToString();var concurrent=await Task.WhenAll(Enumerable.Range(0,100).Select(i=>api.ReserveAsync(session,request,concurrentKey,CancellationToken.None)));
                Program.Check(concurrent.Count(x=>x.ResponseHttpStatus==201)==1 && concurrent.Count(x=>x.ResponseHttpStatus==200)==99,"real 100 concurrent same-key reserve: one 201 and 99 200");Program.Check(concurrent.Select(x=>x.RawJson).Distinct().Count()==1,"real 100 concurrent reserves return byte-identical success JSON");
                await SendReplayResult(api,auth,clock,identity,concurrent[0],"fail");
                var originalReserve=await api.ReserveAsync(await auth.EnsureAsync(),request,key,CancellationToken.None);Program.Check(originalReserve.RawJson==reserve.RawJson,"reserve raw snapshot survives later attempt consumption");
                var originalResult=await api.SendResultAsync(await auth.EnsureAsync(),context.ChallengeId,metadata,null,resultKey,CancellationToken.None);Program.Check(originalResult.RawJson==accepted.RawJson,"result raw snapshot survives later attempt consumption");
                var exhausted=await api.GetStatusAsync(await auth.EnsureAsync(),gate,CancellationToken.None);Program.Check(exhausted.Eligible && exhausted.RemainingAttempts==0 && exhausted.ReasonCode=="attempts_exhausted","status reports true current remaining attempts after concurrency");
            }
        }
        private static async Task SendReplayResult(ScoreManagerApiClient api,AuthenticationSession auth,IClock clock,TicketProvider identity,ReserveResponse reserve,string endType) {
            var context=new ChallengeContext {ChallengeId=reserve.ChallengeId,OwnerSid=identity.CurrentSid,ScoreServerBaseUrl=auth.Endpoint.NormalizedUrl,Map=reserve.Map,ResultAcceptUntil=reserve.ResultAcceptUntil,ClientVersion="JBSLViewer/integration",Started=true,GameplayGeneration=1,Timing=new ResultTiming {StartedAtClient=clock.UtcNow,LocalSongDurationSeconds=180,SongSpeedMultiplier=1}};context.Submission.MarkStarted(true);
            await api.StartedAsync(await auth.EnsureAsync(),context.ChallengeId,new StartedRequest {ActualMap=context.Map,SubmissionAllowed=true,StartedAtClient=clock.UtcNow},CancellationToken.None);
            // Synthetic measurements exercise production serialization; this is not a real gameplay recording.
            const string gameVersion="1.29.1_4575554838";
            var replay=new Replay();replay.info.gameVersion=gameVersion;replay.info.version="JBSLViewer/integration";replay.info.playerID=identity.CurrentSid;replay.info.playerName="通信検証";replay.info.platform="steam";replay.info.hash=context.Map.Hash;replay.info.mode=context.Map.Characteristic;replay.info.difficulty=context.Map.Difficulty;replay.info.speed=1;replay.info.score=endType=="clear"?115:0;
            replay.frames.Add(new Frame {time=1,fps=90,head=new Transform(),leftHand=new Transform(),rightHand=new Transform()});
            replay.notes.Add(new NoteEvent {noteID=0,eventTime=1,spawnTime=0.5f,eventType=endType=="clear"?NoteEventType.good:NoteEventType.miss,noteCutInfo=new NoteCutInfo {speedOK=true,directionOK=true,saberTypeOK=true,beforeCutRating=1,afterCutRating=1}});
            byte[] gzip;using(var buffer=new MemoryStream()) { using(var stream=new GZipStream(buffer,CompressionMode.Compress,true)) { var raw=ReplayEncoder.Encode(replay);stream.Write(raw,0,raw.Length); } gzip=buffer.ToArray(); }
            var observed=new ResultMetadata {GameVersion=gameVersion,ModifiedScore=replay.info.score,MultipliedScore=replay.info.score,MaxPossibleModifiedScore=115,GoodCutsCount=endType=="clear"?1:0,MissedCount=endType=="fail"?1:0,BadCutsCount=0,MaxCombo=endType=="clear"?1:0,FullCombo=endType=="clear",Energy=endType=="clear"?0.5:0,EndSongTime=1,Modifiers=new string[0],Timing=new ResultTiming {EndedAtClient=clock.UtcNow,TotalPauseSeconds=0}};
            var snapshot=QualifierResultFactory.Create(context,endType,observed,gzip,clock);var outbox=new QualifierOutbox(new OutboxStore(Path.Combine(Path.GetTempPath(),"jbsl-http-replay-"+Guid.NewGuid())),api,auth,clock);var entry=await outbox.EnqueueAsync(context,snapshot);var metadata=entry.MetadataJson;var key=entry.IdempotencyKey;
            await outbox.RetryAsync(false);var saved=outbox.Entries.Single();Program.Check(!outbox.HasUnresolved && saved.State=="sent" && saved.Response.Status=="submitted" && saved.Response.ValidForRanking && saved.Response.ReplaySha256!=null,"real production BSOR gzip "+endType+" result accepted for ranking with build-qualified game version");
            var duplicate=await api.SendResultAsync(await auth.EnsureAsync(),context.ChallengeId,metadata,gzip,key,CancellationToken.None);Program.Check(duplicate.RawJson==saved.ResponseJson,"real BSOR "+endType+" repeated result preserves raw JSON");
        }
    }
}

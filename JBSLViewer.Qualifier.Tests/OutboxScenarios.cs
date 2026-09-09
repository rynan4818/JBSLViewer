using System;
using System.Linq;
using System.Threading.Tasks;
using System.Threading;
using JBSLViewer.Qualifier.Core;
using JBSLViewer.Qualifier.Core.Contracts;
using JBSLViewer.Qualifier.Core.Outbox;
namespace JBSLViewer.Qualifier.Tests {
    internal static class OutboxScenarios {
        private sealed class FailingStore : OutboxStore { public bool Fail=true;public FailingStore(string p):base(p){}public override void Save(OutboxEntry e) { if(Fail) throw new System.IO.IOException("injected");base.Save(e); } }
        private sealed class DelayedStore : OutboxStore { public ManualResetEventSlim Entered=new ManualResetEventSlim();public ManualResetEventSlim Release=new ManualResetEventSlim();private int _calls;public DelayedStore(string p):base(p){}public override void Save(OutboxEntry e) { if(Interlocked.Increment(ref _calls)==1) {Entered.Set();Release.Wait();}base.Save(e); } }
        private sealed class DeleteFailStore : OutboxStore { public bool Fail;public DeleteFailStore(string p):base(p){}protected override void AtomicWrite(string path,string data) { if(Fail && System.IO.Path.GetFileName(path)=="deleted.json") throw new System.IO.IOException("injected delete failure");base.AtomicWrite(path,data); } }
        public static async Task Run() {
            using(var r=new Rig()) {
                var store=new FailingStore(r.Store.DirectoryPath) {Fail=false};var outbox=new QualifierOutbox(store,r.Api,r.Auth,r.Clock);var c=r.Context();await outbox.EnqueueAsync(c,QualifierResultFactory.Create(c,"quit",null,null,r.Clock));r.Api.Result=(s,id,m,b,k)=>{store.Fail=true;throw new ApiException(409,"result_acceptance_expired",false);};await outbox.RetryAsync(true);Program.Check(outbox.Entries[0].State=="save_failed","final rejection disk failure remains recoverable");store.Fail=false;await outbox.RetryAsync(true);Program.Check(outbox.Entries[0].State=="stopped" && r.Api.ResultCalls==1,"saving terminal state after disk failure cannot re-send final rejection");
            }
            using(var r=new Rig()) {
                var store=new DelayedStore(r.Store.DirectoryPath);var outbox=new QualifierOutbox(store,r.Api,r.Auth,r.Clock);var c=r.Context();var save=outbox.EnqueueAsync(c,QualifierResultFactory.Create(c,"quit",null,null,r.Clock));
                Program.Check(store.Entered.Wait(2000),"delayed first durable save entered");var retry=outbox.RetryAsync(true);await Task.Delay(30);Program.Check(r.Api.ResultCalls==0 && !outbox.GetSummaries()[0].Persisted,"concurrent Retry cannot send before first save completes");store.Release.Set();await save;await retry;Program.Check(r.Api.ResultCalls==1,"concurrent Retry sends only after durable save");
            }
            using(var r=new Rig()) {
                var store=new DeleteFailStore(r.Store.DirectoryPath);var outbox=new QualifierOutbox(store,r.Api,r.Auth,r.Clock);var c=r.Context();await outbox.EnqueueAsync(c,QualifierResultFactory.Create(c,"quit",null,null,r.Clock));store.Fail=true;
                try { await outbox.ForceClearAsync();throw new Exception("delete unexpectedly succeeded"); } catch(System.IO.IOException) { }
                Program.Check(!store.IsDeleted(c.ClientResultId) && outbox.HasUnresolved,"failed tombstone write leaves memory and durable result recoverable");store.Fail=false;await outbox.RetryAsync(true);Program.Check(r.Api.ResultCalls==1,"result still sendable after failed clear");
            }
            using(var r=new Rig()) {
                var c=r.Context();var result=QualifierResultFactory.Create(c,"preflight_rejected",null,null,r.Clock);var e=await r.Outbox.EnqueueAsync(c,result);
                Program.Check(r.Api.ResultCalls==0 && e.Persisted,"enqueue persists without sending");
                var envelope=StrictJson.Object(System.IO.File.ReadAllText(System.IO.Path.Combine(r.Store.DirectoryPath,e.Id+".json")));
                Program.Check(envelope["scoreServerBaseUrl"]?.ToString()==e.ScoreServerBaseUrl && envelope["blockedReason"]!=null && !e.MetadataJson.Contains("scoreServerBaseUrl"),"endpoint uses required local envelope keys only");
                var restored=new QualifierOutbox(new OutboxStore(r.Store.DirectoryPath),r.Api,r.Auth,r.Clock);Program.Check(restored.Entries.Count==1 && restored.Entries[0].MetadataJson==e.MetadataJson,"restart restores identical metadata");
                r.Auth.Configure("http://127.0.0.1:18082/Base",true);await restored.RetryAsync(true);Program.Check(r.Api.AuthCalls==0 && r.Api.ResultCalls==0 && restored.Entries[0].BlockedReason=="server_mismatch","different port/path prevents recovery auth and send");
                r.Auth.Configure("http://127.0.0.1:18081",true);r.Identity.CurrentSid="B";await restored.RetryAsync(true);Program.Check(r.Api.ResultCalls==0,"different sid cannot send outbox");r.Identity.CurrentSid=c.OwnerSid;r.Auth.RefreshIdentity();
                var attempts=0;r.Api.Result=(s,id,m,b,k)=>{attempts++;if(attempts==1) throw new ApiException(401,"authentication_required",false);Program.Check(m==e.MetadataJson && k==e.IdempotencyKey,"401 retry keeps payload and result key");return Task.FromResult(new ResultResponse {ChallengeId=id,Status="submitted"});};
                await restored.RetryAsync(true);Program.Check(attempts==2 && !restored.HasUnresolved,"401 false retryable still reauthenticates once");
            }
            using(var r=new Rig()) {
                var store=new FailingStore(r.Store.DirectoryPath);var outbox=new QualifierOutbox(store,r.Api,r.Auth,r.Clock);var c=r.Context();await outbox.EnqueueAsync(c,QualifierResultFactory.Create(c,"quit",null,null,r.Clock));await outbox.RetryAsync();Program.Check(r.Api.ResultCalls==0 && outbox.Entries[0].State=="save_failed","failed save retains memory and prohibits sending");store.Fail=false;await outbox.RetryAsync(true);Program.Check(r.Api.ResultCalls==1 && !outbox.HasUnresolved,"manual save retry recovers");
            }
            using(var r=new Rig()) {
                var c=r.Context();await r.Outbox.EnqueueAsync(c,QualifierResultFactory.Create(c,"unknown",null,null,r.Clock));var response=new TaskCompletionSource<ResultResponse>();r.Api.Result=(s,id,m,b,k)=>response.Task;var sending=r.Outbox.RetryAsync(true);await Task.Delay(30);await r.Outbox.ForceClearAsync();response.SetResult(new ResultResponse {ChallengeId=c.ChallengeId,Status="submitted"});await sending;
                Program.Check(!r.Outbox.HasUnresolved && r.Outbox.Entries.Count==0,"clear while sending blocks late response resurrection");Program.Check(new OutboxStore(r.Store.DirectoryPath).Load().Count==0,"tombstone survives restart");
            }
            using(var r=new Rig()) {
                var c=r.Context();await r.Outbox.EnqueueAsync(c,QualifierResultFactory.Create(c,"fail",null,null,r.Clock));r.Api.Result=(s,id,m,b,k)=>{throw new ApiException(409,"result_acceptance_expired",false);};await r.Outbox.RetryAsync(true);Program.Check(r.Outbox.Entries.Single().State=="stopped","explicit final rejection stopped");var calls=r.Api.ResultCalls;r.Identity.CurrentSid="B";await r.Outbox.RetryAsync(true);r.Identity.CurrentSid=c.OwnerSid;await r.Outbox.RetryAsync(true);Program.Check(r.Outbox.Entries.Single().State=="stopped" && r.Outbox.Entries.Single().ErrorCode=="result_acceptance_expired","owner switch preserves final stopped reason");await r.Outbox.RetryAsync(true);Program.Check(r.Api.ResultCalls==calls,"stopped results not automatically or manually resent");await r.Outbox.ForceClearAsync();Program.Check(!r.Outbox.HasUnresolved,"explicit local clear releases stopped result");
            }
        }
    }
}

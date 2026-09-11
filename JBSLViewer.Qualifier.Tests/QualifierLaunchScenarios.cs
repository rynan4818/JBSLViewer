using System;
using System.Collections.Concurrent;
using System.Threading;
using System.Threading.Tasks;
using JBSLViewer.Qualifier.Core;
using JBSLViewer.Qualifier.Core.Contracts;
using JBSLViewer.Qualifier.UI;

namespace JBSLViewer.Qualifier.Tests
{
    internal static class QualifierLaunchScenarios
    {
        internal static async Task Run()
        {
            await Challenge();
            await Practice();
            await Preparation();
            await CallbackOrdering();
        }

        private static async Task Challenge()
        {
            using (var rig = new LaunchRig())
            {
                Task<bool> launch = null;
                rig.Queue(() =>
                {
                    launch = rig.StartChallenge();
                    Program.Check(rig.Direct.Preparing && rig.Room.IsOpen && rig.Engine.Calls.Count == 0,
                        "direct preparation retains the room before committing gameplay");
                });
                Program.Check(!launch.IsCompleted && rig.Engine.Calls.Count == 1 && rig.Solo.PlayCalls == 0,
                    "challenge invokes the game directly once and still waits for gameplay arrival");
                var call = rig.Engine.Calls[0];
                Program.Check(call.Mode == "Solo" && call.Beatmap == rig.Map && call.Preview == rig.Map.level && call.Practice == null,
                    "direct challenge starts the exact loaded map as a full standard play");
                Program.Check(call.Environment == rig.Setup.environmentOverrideSettings && call.Colors == rig.Setup.colorSchemesSettings.Color
                    && call.Modifiers == rig.Setup.gameplayModifiers && call.Settings == rig.Setup.playerSettings,
                    "direct launch carries the configured environment, colors, modifiers and player settings");
                Program.Check(rig.Tracker.Tracks == 1 && rig.Runtime.OrdinaryStarts == 0, "challenge keeps one submission owner");
                rig.Queue(rig.Arrive);
                Program.Check(await launch && StandardPlayAdapter.Pending == null, "gameplay acknowledgement completes the challenge launch");
                rig.Adapter.Arrived(rig.Context);
                rig.Finish(LevelCompletionResults.LevelEndStateType.Cleared);
                Program.Check(rig.Entry.Returns.Count == 1 && !rig.Entry.Returns[0].Practice && rig.Entry.Returns[0].ShowResults
                    && rig.Room.ShowingResults && rig.Room.IsOpen && !rig.Room.LaunchPending,
                    "cleared challenge returns one result to the existing room");
                call.Finished(new StandardLevelScenesTransitionSetupDataSO(), Result(LevelCompletionResults.LevelEndStateType.Failed));
                rig.Direct.Tick();
                Program.Check(rig.Entry.Returns.Count == 1 && rig.Tracker.Tracks == 1, "duplicate finish cannot show or track another result");
            }
            using (var rig = new LaunchRig())
            {
                rig.Entry.OwnsSelection = false;
                rig.Solo.OnPlay = rig.Arrive;
                Program.Check(await rig.StartChallenge() && rig.Solo.PlayCalls == 1 && rig.Engine.Calls.Count == 0,
                    "existing native selection calls retain their standard launch path");
            }
        }

        private static async Task Practice()
        {
            foreach (var state in new[] { LevelCompletionResults.LevelEndStateType.Cleared, LevelCompletionResults.LevelEndStateType.Failed })
            using (var rig = new LaunchRig())
            {
                Task practice = null;
                rig.Queue(() => practice = rig.Direct.StartPracticeAsync());
                await practice;
                Program.Check(rig.Engine.Calls.Count == 1 && rig.Engine.Calls[0].Practice == null && rig.Solo.PlayCalls == 0,
                    state + ": PRACTICE starts full play without a native practice selection screen");
                Program.Check(rig.Runtime.OrdinaryStarts == 1 && rig.Tracker.Tracks == 0 && rig.Runtime.ActiveChallenge == null,
                    state + ": PRACTICE uses no challenge reservation or submission owner");
                rig.Room.GameplayStarted();
                rig.Finish(state);
                Program.Check(rig.Entry.Returns.Count == 1 && rig.Entry.Returns[0].Practice && rig.Entry.Returns[0].ShowResults
                    && rig.Room.ShowingResults && rig.Room.Map.Equals(rig.Map.Key), state + ": PRACTICE preserves the selected map for results");
                rig.Queue(() => practice = rig.Direct.StartPracticeAsync());
                await practice;
                Program.Check(rig.Engine.Calls.Count == 1, "results must close before another practice starts");
                rig.Room.Resume(); // Results CONTINUE/RESTART restores the detail before another play.
                rig.Queue(() => practice = rig.Direct.StartPracticeAsync());
                await practice;
                Program.Check(rig.Engine.Calls.Count == 2 && rig.Tracker.Tracks == 0 && rig.Runtime.OrdinaryStarts == 2,
                    "practice result restart creates another ordinary full play without consuming a challenge");
            }
            using (var rig = new LaunchRig())
            {
                Task practice = null;
                rig.Queue(() => practice = rig.Direct.StartPracticeAsync()); await practice;
                rig.Room.GameplayStarted(); rig.Finish(LevelCompletionResults.LevelEndStateType.Incomplete, LevelCompletionResults.LevelEndAction.Quit);
                Program.Check(rig.Room.IsOpen && !rig.Room.LaunchPending && !rig.Room.ShowingResults && rig.Entry.Returns.Count == 1
                    && !rig.Entry.Returns[0].ShowResults, "quitting practice returns to the retained detail without results");
            }
            using (var rig = new LaunchRig())
            {
                rig.Runtime.SelectionLocked = true;
                await rig.Direct.StartPracticeAsync();
                rig.Runtime.SelectionLocked = false; rig.Runtime.ActiveChallenge = rig.Context;
                await rig.Direct.StartPracticeAsync();
                Program.Check(rig.Engine.Calls.Count == 0 && !rig.Room.LaunchPending, "practice cannot replace an active or reserving challenge");
            }
        }

        private static async Task Preparation()
        {
            foreach (var change in new Action<LaunchRig>[] {
                rig => rig.Entry.SelectedBeatmap = new TestBeatmap("Expert"),
                rig => rig.Map.Difficulty = "Expert",
                rig => rig.Runtime.AllowStart = false,
                rig => rig.Runtime.SceneTransitioning = true,
                rig => rig.Entry.Ready = false })
            using (var rig = new LaunchRig())
            {
                Task<bool> launch = null;
                rig.Queue(() => { launch = rig.StartChallenge(); change(rig); });
                Program.Check(!await launch && rig.Engine.Calls.Count == 0 && !rig.Room.LaunchPending && rig.Tracker.Detaches == 1,
                    "changed selection, eligibility or transition readiness prevents direct invocation and releases tracking");
            }
            using (var rig = new LaunchRig())
            {
                Task<bool> launch = null;
                rig.Queue(() => { launch = rig.StartChallenge(); Program.Check(rig.Direct.CancelPreparation(), "back cancels before direct invocation"); rig.Adapter.FailExplicitly(); });
                Program.Check(!await launch && rig.Engine.Calls.Count == 0 && rig.Tracker.Detaches == 1 && rig.Room.Notice.Contains("中止"),
                    "cancellation releases the launch once and keeps its explanation");
                rig.Adapter.FailExplicitly(); rig.Direct.Tick();
                Program.Check(rig.Tracker.Detaches == 1, "repeated cancellation does not detach twice");
            }
            using (var rig = new LaunchRig())
            {
                Task first = null, second = null;
                rig.Queue(() => { first = rig.Direct.StartPracticeAsync(); rig.Direct.CancelPreparation(); second = rig.Direct.StartPracticeAsync(); });
                await first; await second;
                Program.Check(rig.Engine.Calls.Count == 1 && rig.Room.LaunchPending && rig.Entry.Returns.Count == 1,
                    "a cancelled practice continuation cannot invoke or reject the later practice");
                Program.Check(!rig.Direct.CancelPreparation(), "back cannot cancel a committed gameplay transition");
            }
            using (var rig = new LaunchRig())
            {
                Task<bool> first = null, duplicate = null;
                rig.Engine.OnStart = _ => rig.Arrive();
                rig.Queue(() => { first = rig.StartChallenge(); duplicate = rig.StartChallenge(); });
                Program.Check(await first && !await duplicate && rig.Engine.Calls.Count == 1 && rig.Tracker.Tracks == 1,
                    "double clicking a challenge starts and tracks only one play");
            }
            using (var rig = new LaunchRig())
            {
                Task<bool> launch = null;
                rig.Engine.OnStart = _ => throw new InvalidOperationException("Native start failed");
                rig.Queue(() => launch = rig.StartChallenge());
                Program.Check(!await launch && rig.Tracker.Detaches == 1 && !rig.Room.LaunchPending && rig.Entry.Returns.Count == 1,
                    "native start exceptions unlock the detail and release the reserved launch");
            }
            using (var rig = new LaunchRig())
            {
                Task<bool> launch = null;
                rig.Queue(() => { launch = rig.StartChallenge(); rig.Room.Select(3024, rig.Map.Key); });
                Program.Check(!await launch && rig.Engine.Calls.Count == 0 && !rig.Room.LaunchPending && !rig.Direct.Preparing
                    && rig.Room.LeagueId == 3024 && rig.Entry.Returns.Count == 0,
                    "a changed room generation releases stale preparation without restoring the old selection");
            }
            using (var rig = new LaunchRig())
            {
                Task<bool> launch = null;
                rig.Queue(() => { launch = rig.StartChallenge(); rig.Room.Close(); });
                Program.Check(!await launch && !rig.Room.IsOpen && !rig.Direct.Preparing && rig.Entry.Returns.Count == 0,
                    "room closure during preparation cancels without reopening the closed flow");
            }
        }

        private static async Task CallbackOrdering()
        {
            using (var rig = new LaunchRig())
            {
                Task practice = null;
                rig.Queue(() => practice = rig.Direct.StartPracticeAsync()); await practice;
                var old = rig.Engine.Calls[0];
                rig.Room.GameplayStarted(); rig.Finish(LevelCompletionResults.LevelEndStateType.Incomplete, LevelCompletionResults.LevelEndAction.Quit);
                rig.Queue(() => practice = rig.Direct.StartPracticeAsync()); await practice;
                old.Finished(new StandardLevelScenesTransitionSetupDataSO(), Result(LevelCompletionResults.LevelEndStateType.Failed));
                old.Restarted(new LevelScenesTransitionSetupDataSO(), Result(LevelCompletionResults.LevelEndStateType.Incomplete, LevelCompletionResults.LevelEndAction.Restart));
                rig.Direct.Tick();
                Program.Check(rig.Room.LaunchPending && rig.Entry.Returns.Count == 1 && rig.Runtime.OrdinaryRestarts == 0,
                    "late finish and restart callbacks from an earlier play cannot alter the current play");
            }
            using (var rig = new LaunchRig())
            {
                Task<bool> launch = null;
                rig.Queue(() => launch = rig.StartChallenge());
                rig.Queue(() => { for (var tick = 0; tick < 1000; tick++) rig.Direct.Tick(); });
                Program.Check(!launch.IsCompleted && rig.Entry.Returns.Count == 0,
                    "loading duration alone cannot fail an unacknowledged launch");
                rig.Queue(() => { rig.Direct.MenuActivated(); rig.Direct.Tick(); });
                Program.Check(!await launch && rig.Tracker.Detaches == 1 && rig.Entry.Returns.Count == 0,
                    "an actual menu return without gameplay arrival releases the adapter before unlocking the room");
                rig.Runtime.SelectionLocked = false; rig.Direct.Tick(); rig.Direct.Tick();
                Program.Check(rig.Entry.Returns.Count == 1 && !rig.Room.LaunchPending && !rig.Room.ShowingResults
                    && rig.Entry.Returns[0].Notice.Contains("without a result"), "missing completion returns one status message after the coordinator unlocks");
            }
            using (var rig = new LaunchRig())
            {
                Task<bool> launch = null;
                rig.Engine.OnStart = _ => rig.Arrive();
                rig.Queue(() => launch = rig.StartChallenge()); Program.Check(await launch, "restart scenario reached gameplay");
                // Models the existing observer sealing/detaching the challenge before native replacement.
                rig.Tracker.Detach(rig.Context.Submission); rig.Runtime.ActiveChallenge = null;
                rig.Engine.Calls[0].Restarted(new LevelScenesTransitionSetupDataSO(), Result(LevelCompletionResults.LevelEndStateType.Incomplete, LevelCompletionResults.LevelEndAction.Restart));
                Program.Check(rig.Room.Practice && rig.Runtime.OrdinaryRestarts == 1 && rig.Tracker.Tracks == 1,
                    "an externally forced challenge restart becomes ordinary play without reusing the reservation");
                rig.Room.GameplayStarted(); rig.Finish(LevelCompletionResults.LevelEndStateType.Cleared);
                Program.Check(rig.Entry.Returns.Count == 1 && rig.Entry.Returns[0].Practice, "replacement gameplay returns a practice result");
            }
            using (var rig = new LaunchRig())
            {
                Task practice = null;
                rig.Queue(() => practice = rig.Direct.StartPracticeAsync()); await practice;
                rig.Entry.MenuVisible = false; rig.Runtime.SceneTransitioning = true;
                rig.Room.GameplayStarted(); rig.Finish(LevelCompletionResults.LevelEndStateType.Failed);
                Program.Check(rig.Entry.Returns.Count == 0, "completion cannot present results during the scene transition");
                rig.Runtime.SceneTransitioning = false; rig.Direct.Tick();
                Program.Check(rig.Entry.Returns.Count == 0, "completion waits until its own challenge flow is visible");
                rig.Entry.MenuVisible = true; rig.Direct.Tick();
                Program.Check(rig.Entry.Returns.Count == 1 && rig.Room.ShowingResults, "result is delivered after menu hierarchy restoration");
            }
        }

        private static LevelCompletionResults Result(LevelCompletionResults.LevelEndStateType state,
            LevelCompletionResults.LevelEndAction action = LevelCompletionResults.LevelEndAction.None)
            => new LevelCompletionResults { levelEndStateType = state, levelEndAction = action };

        private sealed class QueuedContext : SynchronizationContext
        {
            private readonly ConcurrentQueue<Action> _callbacks = new ConcurrentQueue<Action>();
            public override void Post(SendOrPostCallback callback, object state) => _callbacks.Enqueue(() => callback(state));
            public void Drain() { while (_callbacks.TryDequeue(out var callback)) callback(); }
        }
        private sealed class LaunchRig : IDisposable
        {
            internal readonly QualifierRoomState Room = new QualifierRoomState();
            internal readonly QualifierRuntime Runtime = new QualifierRuntime();
            internal readonly SoloFreePlayFlowCoordinator Solo = new SoloFreePlayFlowCoordinator();
            internal readonly SubmissionEligibilityTracker Tracker = new SubmissionEligibilityTracker();
            internal readonly TestBeatmap Map = new TestBeatmap("ExpertPlus");
            internal readonly GameplaySetupViewController Setup = new GameplaySetupViewController();
            internal readonly MenuTransitionsHelper Engine = new MenuTransitionsHelper();
            internal readonly QualifierMenuEntry Entry;
            internal readonly QualifierDirectPlayController Direct;
            internal readonly StandardPlayAdapter Adapter;
            internal readonly ChallengeContext Context;
            private readonly QueuedContext _queue = new QueuedContext();
            internal LaunchRig()
            {
                Room.Open(3023, Map.Key);
                Entry = new QualifierMenuEntry(Room, Map);
                Direct = new QualifierDirectPlayController(Entry, Room, Runtime, Setup, Engine);
                Adapter = new StandardPlayAdapter(Solo, Tracker, Runtime, Direct);
                Context = new ChallengeContext { Map = Map.Key, Submission = new SubmissionHistory() };
                Adapter.Initialize();
            }
            internal Task<bool> StartChallenge()
            {
                Runtime.ActiveChallenge = Context; Runtime.SelectionLocked = true;
                return Adapter.StartAsync(Context);
            }
            internal void Arrive() { Room.GameplayStarted(); Adapter.Arrived(Context); Runtime.SelectionLocked = false; }
            internal void Queue(Action action)
            {
                var previous = SynchronizationContext.Current;
                try { SynchronizationContext.SetSynchronizationContext(_queue); action(); _queue.Drain(); }
                finally { SynchronizationContext.SetSynchronizationContext(previous); }
            }
            internal void Finish(LevelCompletionResults.LevelEndStateType state,
                LevelCompletionResults.LevelEndAction action = LevelCompletionResults.LevelEndAction.None)
            {
                Tracker.Detach(Context.Submission); Runtime.ActiveChallenge = null; Room.GameplayFinished();
                Engine.Calls[Engine.Calls.Count - 1].Finished(new StandardLevelScenesTransitionSetupDataSO(), Result(state, action));
                Direct.Tick();
            }
            public void Dispose() { Adapter.FailExplicitly(); Adapter.Dispose(); Direct.Dispose(); }
        }
    }
}

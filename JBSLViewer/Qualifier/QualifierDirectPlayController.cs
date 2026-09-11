/*
Portions copied/adapted from TournamentAssistant.
Source: https://github.com/MatrikMoon/TournamentAssistant?tab=MIT-1-ov-file
Original: TournamentAssistant/Utilities/SongUtils.cs (PlaySong); TournamentAssistant/UI/FlowCoordinators/QualifierCoordinator.cs (practice and finish callbacks)
Revision: ab4021a49f889bc36059efe3d8a2431097f1ffa5

MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
*/
using System;
using System.Threading.Tasks;
using JBSLViewer.Qualifier.Core;
using JBSLViewer.Qualifier.UI;
using Zenject;

namespace JBSLViewer.Qualifier
{
    public sealed class QualifierDirectPlayResult
    {
        public bool Practice;
        public IDifficultyBeatmap Beatmap;
        public IReadonlyBeatmapData TransformedBeatmap;
        public LevelCompletionResults Completion;
        public string Notice;
        public bool ShowResults => Completion != null
            && Completion.levelEndAction != LevelCompletionResults.LevelEndAction.Quit
            && Completion.levelEndAction != LevelCompletionResults.LevelEndAction.Restart
            && (Completion.levelEndStateType == LevelCompletionResults.LevelEndStateType.Cleared
                || Completion.levelEndStateType == LevelCompletionResults.LevelEndStateType.Failed);
    }

    public sealed class QualifierDirectPlayController : ITickable, IDisposable
    {
        private sealed class Operation
        {
            public long Id, Generation;
            public bool Practice, Invoked, Finished, MenuReturned;
            public ChallengeContext Challenge;
            public IDifficultyBeatmap Beatmap;
            public QualifierDirectPlayResult Result;
        }
        private readonly QualifierMenuEntry _entry;
        private readonly QualifierRoomState _room;
        private readonly QualifierRuntime _runtime;
        private readonly GameplaySetupViewController _setup;
        private readonly MenuTransitionsHelper _transitions;
        private Operation _current;
        private bool _disposed;
        public bool FromRoom => _entry.OwnsSelection;
        public bool Preparing => _current != null && !_current.Invoked && !_current.Finished;
        public string Status => Preparing ? "Preparing direct play...  (<: cancel)" : null;

        public QualifierDirectPlayController(QualifierMenuEntry entry, QualifierRoomState room, QualifierRuntime runtime,
            GameplaySetupViewController setup, MenuTransitionsHelper transitions)
        { _entry = entry; _room = room; _runtime = runtime; _setup = setup; _transitions = transitions; }

        public Task<bool> StartChallengeAsync(ChallengeContext context) => StartAsync(false, context);
        public async Task StartPracticeAsync()
        {
            if (_runtime.SelectionLocked || _runtime.ActiveChallenge != null) return;
            await StartAsync(true, null);
        }
        private bool Current(Operation operation) => ReferenceEquals(_current, operation)
            && _room.IsCurrentLaunch(operation.Id) && _room.Generation == operation.Generation;

        private async Task<bool> StartAsync(bool practice, ChallengeContext context)
        {
            if (_disposed || _current != null || !_entry.SelectionReady || _runtime.SceneTransitioning) return false;
            if (!practice && (context == null || !_runtime.MenuCanStart(context))) return false;
            var beatmap = _entry.SelectedBeatmap;
            if (beatmap == null || !_entry.BeginDirectLaunch(practice)) return false;
            var operation = new Operation { Id = _room.LaunchId, Generation = _room.Generation,
                Practice = practice, Challenge = context, Beatmap = beatmap };
            _current = operation;
            QualifierMenuController.Instance?.ApplyLock();
            Plugin.Log.Info("Challenge launch: preparing direct " + (practice ? "practice" : "challenge"));
            // Permit cancellation before committing the scene transition. A stale
            // continuation cannot invoke or reject another operation.
            await Task.Yield();
            if (!Current(operation)) { ReleaseStale(operation); return false; }
            try
            {
                var selected = _entry.SelectedBeatmap;
                if (!_entry.SelectionReady || _runtime.SceneTransitioning || !ReferenceEquals(selected, beatmap)
                    || !Equals(QualifierGameplayObserver.ReadMap(beatmap), _room.Map)
                    || (!practice && !_runtime.MenuCanStart(context))
                    || (practice && (_runtime.SelectionLocked || _runtime.ActiveChallenge != null)))
                {
                    Reject(operation, "The selected map or account changed before starting.");
                    return false;
                }
                var environment = _setup.environmentOverrideSettings;
                var colors = _setup.colorSchemesSettings.GetOverrideColorScheme();
                var modifiers = _setup.gameplayModifiers;
                var settings = _setup.playerSettings;
                if (practice) _runtime.OrdinaryPlayRequested();
                operation.Invoked = true;
                Plugin.Log.Info("Challenge launch: starting directly from the challenge room");
                // TA starts the loaded beatmap here without presenting a Solo flow.
                // JBSL's reservation and gameplay observer remain responsible for
                // challenge ownership, eligibility, replay capture and submission.
                _transitions.StartStandardLevel("Solo", beatmap, beatmap.level, environment, colors,
                    modifiers, settings, null, "Menu", false, false, null,
                    (transition, result) => Finished(operation, transition, result),
                    (transition, result) => Restarted(operation));
                return true;
            }
            catch (Exception ex)
            {
                Plugin.Log.Error("Challenge direct start failed: " + ex);
                if (Current(operation)) Reject(operation, "The selected map could not start.");
                return false;
            }
        }

        public bool CancelPreparation()
        {
            if (!Preparing || _runtime.SceneTransitioning) return false;
            Reject(_current, "プレイ開始を中止しました。");
            return true;
        }
        public void RejectPending(ChallengeContext context, string message)
        {
            if (_current != null && !_current.Finished && ReferenceEquals(_current.Challenge, context)) Reject(_current, message);
        }
        private void Reject(Operation operation, string message)
        {
            if (!Current(operation)) return;
            _current = null;
            _room.LaunchFailed(message);
            _room.CompleteLaunch(operation.Id, false);
            _entry.ShowDirectResult(new QualifierDirectPlayResult { Practice = operation.Practice, Beatmap = operation.Beatmap, Notice = message });
        }
        private void ReleaseStale(Operation operation)
        {
            if (!ReferenceEquals(_current, operation)) return;
            _current = null;
            StandardPlayAdapter.Pending?.ReturnedWithoutArrival(operation.Challenge);
            // Release only this launch. Closing the room or starting a newer
            // launch must not allow an old callback to reopen or replace it.
            _room.CompleteLaunch(operation.Id, false);
        }
        private void Finished(Operation operation, StandardLevelScenesTransitionSetupDataSO transition, LevelCompletionResults result)
        {
            if (!Current(operation) || operation.Finished) return;
            if (result?.levelEndAction == LevelCompletionResults.LevelEndAction.Restart) return;
            operation.Finished = true;
            operation.Result = new QualifierDirectPlayResult { Practice = operation.Practice, Beatmap = operation.Beatmap,
                TransformedBeatmap = transition?.transformedBeatmapData, Completion = result };
        }
        private void Restarted(Operation operation)
        {
            if (!Current(operation) || operation.Finished) return;
            // An external restart must never reuse a reserved challenge. The
            // gameplay observer seals its result before the replacement scene.
            if (!operation.Practice) _runtime.OrdinaryRestartDetected();
            operation.Practice = true;
            operation.Challenge = null;
            operation.MenuReturned = false;
            _room.RestartAsPractice(operation.Id);
        }
        public void MenuActivated()
        {
            QualifierGameplayObserver.MenuActivated();
            if (_current?.Invoked == true) _current.MenuReturned = true;
        }
        public void Tick()
        {
            var operation = _current;
            if (operation == null) return;
            if (!Current(operation)) { ReleaseStale(operation); return; }
            if (_runtime.SceneTransitioning || !_entry.CanReceiveDirectResult) return;
            if (!operation.Finished && operation.Invoked && operation.MenuReturned)
            {
                // An actual menu reactivation, not elapsed loading time, confirms
                // that gameplay returned without the normal completion callback.
                operation.Finished = true;
                operation.Result = new QualifierDirectPlayResult { Practice = operation.Practice, Beatmap = operation.Beatmap,
                    Notice = "Returned without a result. Check the challenge result status." };
            }
            if (!operation.Finished) return;
            QualifierGameplayObserver.MenuActivated();
            StandardPlayAdapter.Pending?.ReturnedWithoutArrival(operation.Challenge);
            if (_runtime.SelectionLocked) return;
            _current = null;
            if (!_room.CompleteLaunch(operation.Id, operation.Result.ShowResults)) return;
            _entry.ShowDirectResult(operation.Result);
        }
        public void Dispose()
        {
            // Standard scene transitions may dispose menu services. Do not treat
            // an already committed gameplay transition as a failed reservation.
            if (Preparing) CancelPreparation();
            _disposed = true;
        }
    }
}

using System;
using System.Collections.Generic;
using System.Reflection;
using JBSLViewer.Qualifier.Core;
using JBSLViewer.Qualifier.Core.Contracts;
using SiraUtil.Submissions;
using UnityEngine;
using Zenject;

namespace JBSLViewer.Qualifier
{
    public sealed class QualifierGameplayObserver : IInitializable, ITickable, IDisposable
    {
        [Inject] private IQualifierGameplayHost _host;
        [Inject] private SubmissionEligibilityTracker _submission;
        [Inject] private QualifierReplayRecorder _recorder;
        [Inject] private StandardLevelScenesTransitionSetupDataSO _transition;
        [Inject] private GameplayCoreSceneSetupData _setup;
        [Inject] private ScoreController _score;
        [Inject] private GameEnergyCounter _energy;
        [Inject] private ComboController _combo;
        [Inject] private AudioTimeSyncController _time;
        [Inject] private IReadonlyBeatmapData _beatmap;
        [Inject] private GameScenesManager _scenes;
        [Inject] private IGamePause _gamePause;
        [InjectOptional] private Submission _sira;
        [InjectOptional] private IReturnToMenuController _returnToMenu;
        public static QualifierGameplayObserver Current { get; private set; }
        private static long _nextGeneration;
        private long _generation;
        private ChallengeContext _context;
        private bool _finished;
        private bool _scoringStarted;
        private bool _returnPending;
        private string _preflightFailure;
        private MapKey _actualMap;
        private ResultMetadata _lastSample = new ResultMetadata();
        private int? _maxMultipliedScore;
        private GameplayModifiersModelSO _modifiersModel;
        private List<GameplayModifierParamsSO> _modifierParams;
        private bool _disposed;
        private Core.Replay.Replay _disposedReplay;
        private DateTimeOffset? _observedEndTime;
        private bool HasUnfinishedChallenge => _context != null && !_finished;
        public bool IsChallengeActive => HasUnfinishedChallenge && !_disposed;

        public void Initialize()
        {
            QualifierRuntime.Instance?.StandardGameplayStarted();
            _generation = ++_nextGeneration;
            // No old observer or recorder may bind the replacement gameplay scene.
            if (Current != null && Current != this && Current.HasUnfinishedChallenge)
                Current.FinalizeObserved(null, "restart", "gameplay_generation_changed");
            Current = this;
            _context = _host.ActiveChallenge;
            if (_context == null) return;
            _score.scoringForNoteFinishedEvent += ScoringObserved;
            _context.GameplayGeneration = _generation;
            if (_sira != null) SubmissionEligibilityTracker.Register(_sira);
            _submission.Refresh(); // Do not create/reset the history made before Play.
            var observation = _submission.ReadCurrent();
            try { _actualMap = ReadMap(_setup.beatmapKey); }
            catch (Exception) { _actualMap = null; }
            if (_transition.gameMode != "Solo" || _setup.practiceSettings != null) _preflightFailure = "unsupported_gameplay_mode";
            else if (Replay.ReplayModeDetector.BlockingReason() is string replayBlock) _preflightFailure = replayBlock;
            else if (_actualMap == null || !_actualMap.Equals(_context.Map)) _preflightFailure = "actual_map_mismatch";
            else if (!observation.Allowed) _preflightFailure = "submission_disabled_before_scoring";
            _context.Submission.MarkStarted(_preflightFailure == null && observation.Allowed, observation.Blockers);
            _context.Timing.StartedAtClient = DateTimeOffset.UtcNow;
            _context.Timing.LocalSongDurationSeconds = Finite(_setup.beatmapLevel.songDuration);
            _context.Timing.SongSpeedMultiplier = Finite(_setup.gameplayModifiers.songSpeedMul);
            try
            {
                // Read the model used by this ScoreController to match the game's scoring.
                _modifiersModel = _score._gameplayModifiersModel;
                if (_modifiersModel == null) throw new InvalidOperationException("ScoreController has no gameplay modifiers model.");
                _modifierParams = _modifiersModel.CreateModifierParamsList(_setup.gameplayModifiers);
                _maxMultipliedScore = ScoreModel.ComputeMaxMultipliedScoreForBeatmap(_beatmap);
            }
            catch (Exception ex)
            {
                _maxMultipliedScore = null;
                Plugin.Log.Warn("Qualifier max score unavailable: " + ex);
            }
            Sample();
            if (_preflightFailure != null) { RejectBeforeScoring(); return; }
            try { _recorder.Begin(_context, _host); }
            catch (Exception ex) { _recorder.RecordingError(ex); }
            _host.GameplayStarted(_context, _generation);
        }

        public static MapKey ReadMap(BeatmapKey beatmap)
        {
            if (!beatmap.IsValid()) throw new FormatException("Invalid beatmap key.");
            var levelId = beatmap.levelId;
            if (!levelId.StartsWith("custom_level_", StringComparison.Ordinal)) throw new FormatException("Not a custom map.");
            return MapKey.Create(levelId.Substring("custom_level_".Length),
                beatmap.beatmapCharacteristic.serializedName, beatmap.difficulty.ToString());
        }

        public void Tick()
        {
            if (_returnPending && !_scenes.isInTransition)
            {
                _returnPending = false;
                _returnToMenu?.ReturnToMenu();
            }
            if (!IsChallengeActive) return;
            Sample();
            BeforeScoring();
        }
        internal void BeforeScoring()
        {
            if (!IsChallengeActive) return;
            _submission.Refresh();
            if (!_scoringStarted && !_recorder.ScoringStarted && !_submission.ReadCurrent().Allowed)
            { _preflightFailure = "submission_disabled_before_scoring"; RejectBeforeScoring(); }
        }
        internal bool AllowScoring(ScoreController controller, AudioTimeSyncController time,
            List<float> pendingNoteTimes, List<ScoringElement> scoring)
        {
            if (!ReferenceEquals(controller, _score)) return true;
            BeforeScoring();
            // Disabling a MonoBehaviour in its Prefix does not cancel the invocation
            // already in progress. Only this rejected challenge must skip that call.
            if (_preflightFailure != null) return false;
            if (IsChallengeActive && !_scoringStarted)
            {
                // Track the first real scoring operation even when replay capture
                // failed to start. Completion of a cut's swing can occur later.
                var nearest = pendingNoteTimes.Count > 0 ? pendingNoteTimes[0] : float.MaxValue;
                foreach (var element in scoring)
                {
                    if (element.time >= time.songTime + .15f && element.time <= nearest) break;
                    if (element is MissScoringElement && element.noteData.scoringType == NoteData.ScoringType.NoScore) continue;
                    _scoringStarted = true;
                    break;
                }
            }
            return true;
        }
        private void ScoringObserved(ScoringElement element)
        {
            if (element is MissScoringElement && element.noteData.scoringType == NoteData.ScoringType.NoScore) return;
            _scoringStarted = true;
        }
        private void RejectBeforeScoring()
        {
            FinalizeObserved(null, "preflight_rejected", _preflightFailure);
            // A scene transition refuses PopScenes while it is already in progress.
            // Freeze gameplay now and wait for that explicit condition, without a timeout.
            _gamePause.Pause();
            if (_returnToMenu != null) _returnPending = true;
            else Plugin.Log.Error("Qualifier preflight rejected but return-to-menu controller was unavailable.");
        }
        private void Sample()
        {
            // Cache independently of Unity objects for unexpected scene teardown fallback.
            _lastSample = new ResultMetadata {
                EndSongTime = Finite(_time.songTime), MultipliedScore = _score.multipliedScore,
                ModifiedScore = _score.modifiedScore, MaxCombo = _combo.maxCombo, Energy = Finite(_energy.energy),
                MaxPossibleModifiedScore = MaxModified(_energy.energy),
                Modifiers = QualifierReplayRecorder.ModifierCodes(_setup.gameplayModifiers, _energy.energy)
            };
        }
        private int? MaxModified(float energy)
        {
            if (!_maxMultipliedScore.HasValue || _modifierParams == null || _modifiersModel == null) return null;
            try { return _modifiersModel.MaxModifiedScoreForMaxMultipliedScore(_maxMultipliedScore.Value, _modifierParams, energy); }
            catch (Exception ex)
            {
                // Stop retrying this optional calculation on every frame after a failure.
                _maxMultipliedScore = null;
                Plugin.Log.Warn("Qualifier max score unavailable: " + ex);
                return null;
            }
        }
        internal void Finish(StandardLevelScenesTransitionSetupDataSO transition, LevelCompletionResults results)
        {
            if (!ReferenceEquals(transition, _transition) || !IsChallengeActive) return;
            FinalizeObserved(results, null, null);
        }
        private void FinalizeObserved(LevelCompletionResults result, string forcedEndType, string failure)
        {
            if (!HasUnfinishedChallenge) return;
            _finished = true;
            if (!_disposed) _score.scoringForNoteFinishedEvent -= ScoringObserved;
            if (!_disposed) _submission.Refresh();
            if (result != null && result.GetType().FullName == "SiraUtil.Submissions.SiraLevelCompletionResults")
            {
                var eligibility = result.GetType().GetProperty("ShouldSubmitScores", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                bool allowed = false;
                try { allowed = eligibility != null && (bool)eligibility.GetValue(result); }
                catch (Exception ex) { Plugin.Log.Warn("Qualifier final submission state unavailable: " + ex.Message); }
                if (!allowed) _context.Submission.Observe(false, new[] { "sirautil_submission_disabled" });
            }
            var end = forcedEndType ?? EndType(result);
            var observed = _lastSample;
            if (result != null)
            {
                observed = new ResultMetadata {
                    EndSongTime = Finite(result.endSongTime), MultipliedScore = result.multipliedScore,
                    ModifiedScore = result.modifiedScore, MaxPossibleModifiedScore = MaxModified(result.energy),
                    MissedCount = result.missedCount, BadCutsCount = result.badCutsCount, GoodCutsCount = result.goodCutsCount,
                    MaxCombo = result.maxCombo, FullCombo = result.fullCombo, Energy = Finite(result.energy),
                    Modifiers = QualifierReplayRecorder.ModifierCodes(result.gameplayModifiers, result.energy)
                };
            }
            observed.EndType = end;
            observed.EndState = end == "clear" ? "cleared" : end == "fail" ? "failed" : end == "unknown" ? "unknown" : "incomplete";
            observed.EndAction = end == "quit" ? "quit" : end == "restart" ? "restart" : end == "unknown" ? "unknown" : "none";
            observed.Map = _context.Map.Copy();
            observed.ClientVersion = _host.ClientVersion;
            observed.GameVersion = Application.version;
            observed.SubmissionEligibility = _context.Submission.ToContract();
            observed.Diagnostics.FailureCode = failure;
            observed.Diagnostics.ActualMap = _actualMap != null && !_actualMap.Equals(_context.Map) ? _actualMap.Copy() : null;
            observed.ScoreValidity.PlayInstanceCount = 1;
            _context.Timing.EndedAtClient = _observedEndTime ?? DateTimeOffset.UtcNow;
            Core.Replay.Replay replay = _disposedReplay;
            if (!_disposed)
            {
                try { replay = _recorder.StopAndDetach(result); }
                catch (Exception ex) { _recorder.RecordingError(ex); _recorder.Dispose(); }
            }
            observed.Diagnostics.ReplayGenerationFailed = _recorder.GenerationFailed;
            _context.Timing.TotalPauseSeconds = _recorder.PauseTrackingAvailable ? (double?)_recorder.TotalPauseSeconds : null;
            observed.Timing = _context.Timing;
            _submission.Detach(_context.Submission);
            // Wrong-map recordings are never attached to a reserved map result.
            if (_actualMap == null || !_actualMap.Equals(_context.Map)) replay = null;
            _host.GameplayFinished(_context, _generation, observed, replay);
            if (end == "restart") _host.OrdinaryRestartDetected();
            _context = null;
        }
        private static string EndType(LevelCompletionResults result)
        {
            if (result == null) return "unknown";
            if (result.levelEndAction == LevelCompletionResults.LevelEndAction.Quit) return "quit";
            if (result.levelEndAction == LevelCompletionResults.LevelEndAction.Restart) return "restart";
            if (result.levelEndStateType == LevelCompletionResults.LevelEndStateType.Cleared) return "clear";
            if (result.levelEndStateType == LevelCompletionResults.LevelEndStateType.Failed) return "fail";
            return "unknown";
        }
        private static double? Finite(float value) => float.IsNaN(value) || float.IsInfinity(value) ? (double?)null : value;
        public void Dispose()
        {
            _score.scoringForNoteFinishedEvent -= ScoringObserved;
            if (IsChallengeActive)
            {
                // Keep only the original generation's cached values. The next gameplay
                // generation resolves this as Restart; return to the menu resolves Unknown.
                _observedEndTime = DateTimeOffset.UtcNow;
                _submission.Refresh();
                _submission.Detach(_context.Submission);
                try { _disposedReplay = _recorder.StopAndDetach(null); }
                catch (Exception ex) { _recorder.RecordingError(ex); _recorder.Dispose(); }
                _disposed = true;
            }
            else if (Current == this) Current = null;
        }

        public static void FlushUnexpectedExit()
        {
            if (Current != null && Current.HasUnfinishedChallenge)
                Current.FinalizeObserved(null, "unknown", "gameplay_disposed_without_finish");
            if (Current?._disposed == true) Current = null;
        }

        internal static void MenuActivated()
        { if (Current?._disposed == true) FlushUnexpectedExit(); }
    }
}

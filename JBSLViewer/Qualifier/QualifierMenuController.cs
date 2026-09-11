using System;
using System.Collections.Generic;
using HarmonyLib;
using HMUI;
using IPA.Utilities;
using JBSLViewer.Models;
using JBSLViewer.Qualifier.Core;
using JBSLViewer.Views;
using UnityEngine;
using Zenject;

namespace JBSLViewer.Qualifier
{
    public sealed class QualifierMenuController : IInitializable, ITickable, IDisposable
    {
        private readonly QualifierRuntime _runtime;
        private readonly PlayerIdentityService _identity;
        private readonly SoloFreePlayFlowCoordinator _solo;
        private readonly StandardLevelDetailViewController _detail;
        private readonly GameplaySetupViewController _setup;
        private readonly LeaderboardPanelViewController _panel;
        private readonly Leaderboard _leaderboard;
        private readonly StandardPlayAdapter _play;
        private readonly UI.QualifierMenuEntry _room;
        private readonly QualifierDirectPlayController _direct;
        private bool _previousRoom;
        private readonly Dictionary<CanvasGroup, Tuple<bool, bool>> _groups = new Dictionary<CanvasGroup, Tuple<bool, bool>>();
        private long _generation;
        private SelectionSnapshot _previous;
        public static QualifierMenuController Instance { get; private set; }
        public bool Locked => _runtime.SelectionLocked || _direct.Preparing;
        public bool Invoking => _play.Invoking;
        public string LaunchStatus => _direct.Status;
        public bool PreparingDirectPlay => _direct.Preparing;
        internal void DirectMenuActivated() => _direct.MenuActivated();
        internal bool CancelPendingLaunch()
        {
            if (!_direct.CancelPreparation()) return false;
            _play.FailExplicitly();
            ApplyLock();
            return true;
        }

        public QualifierMenuController(QualifierRuntime runtime, PlayerIdentityService identity, SoloFreePlayFlowCoordinator solo,
            StandardLevelDetailViewController detail, GameplaySetupViewController setup, LeaderboardPanelViewController panel,
            Leaderboard leaderboard, StandardPlayAdapter play, UI.QualifierMenuEntry room, QualifierDirectPlayController direct)
        { _runtime = runtime; _identity = identity; _solo = solo; _detail = detail; _setup = setup; _panel = panel; _leaderboard = leaderboard; _play = play; _room = room; _direct = direct; }
        public void Initialize()
        {
            Instance = this;
            _detail.didChangeDifficultyBeatmapEvent += DifficultyChanged;
            _detail.didChangeContentEvent += ContentChanged;
            _leaderboard.Updated += BoardUpdated;
            _identity.Changed += SelectionUpdated;
            _runtime.AttachMenu(this);
            SelectionUpdated();
        }
        // GameplaySetupViewController no longer exposes a modifier-changed event.
        // Poll the selection here and recheck it immediately before starting a challenge.
        public void Tick() { SelectionUpdated(); ApplyLock(); }
        private void DifficultyChanged(StandardLevelDetailViewController view) => SelectionUpdated();
        private void ContentChanged(StandardLevelDetailViewController view, StandardLevelDetailViewController.ContentType content)
        {
            // Explicit failed/cancelled level content is a failure, never elapsed loading time.
            if (!_room.OwnsSelection && content == StandardLevelDetailViewController.ContentType.Error) StandardPlayAdapter.Pending?.FailExplicitly();
            SelectionUpdated();
        }
        private void BoardUpdated(int league) { if (_previous?.LeagueId == league) SelectionUpdated(); }
        public bool IsSoloSelection => !_runtime.SceneTransitioning && _solo != null && _solo.isActivated && _solo.childFlowCoordinator == null
            && _solo.topViewController is LevelSelectionNavigationController && _detail.isActivated
            && _detail.gameObject.activeInHierarchy
            && Replay.ReplayModeDetector.BlockingReason() == null;
        public void SelectionUpdated()
        {
            int.TryParse(_panel.JBSLLeagueValue, out var league);
            var fromRoom = _room.OwnsSelection;
            if (fromRoom) league = _room.LeagueId;
            var level = fromRoom ? _room.SelectedBeatmap?.Level : _detail.beatmapLevel;
            Core.Contracts.MapKey key = null;
            try { if (level != null) key = QualifierGameplayObserver.ReadMap(fromRoom ? _room.SelectedBeatmap.Key : _detail.beatmapKey); } catch (Exception) { }
            var duration = level?.songDuration;
            var snapshot = new SelectionSnapshot {
                LeagueId = league, CurrentSid = _identity.CurrentSid, Map = key,
                IsSolo = fromRoom ? _room.SelectionReady && !_runtime.SceneTransitioning && Replay.ReplayModeDetector.BlockingReason() == null : IsSoloSelection,
                SongTitle = level?.songName, LocalSongDurationSeconds = duration.HasValue && duration > 0
                    && !float.IsInfinity(duration.Value) && !float.IsNaN(duration.Value) ? (double?)duration.Value : null,
                SongSpeedMultiplier = _setup.gameplayModifiers?.songSpeedMul,
                Leaderboard = _leaderboard.GetLeaderboardData(league)?.qualifierContract,
                LeaderboardFresh = _leaderboard.IsQualifierCacheFresh(league)
            };
            if (_previous == null || fromRoom != _previousRoom || snapshot.LeagueId != _previous.LeagueId || !Equals(snapshot.Map, _previous.Map)
                || snapshot.IsSolo != _previous.IsSolo || snapshot.CurrentSid != _previous.CurrentSid
                || snapshot.LocalSongDurationSeconds != _previous.LocalSongDurationSeconds
                || snapshot.SongSpeedMultiplier != _previous.SongSpeedMultiplier
                || !ReferenceEquals(snapshot.Leaderboard, _previous.Leaderboard)
                || snapshot.LeaderboardFresh != _previous.LeaderboardFresh)
            {
                snapshot.SelectionGeneration = ++_generation;
                _previousRoom = fromRoom;
                _previous = snapshot;
                _runtime.UpdateSelection(snapshot);
            }
        }
        internal bool CanStart(ChallengeContext context)
        {
            SelectionUpdated();
            if (context == null || _runtime.SceneTransitioning) return false;
            var fromRoom = _room.OwnsSelection;
            Core.Contracts.MapKey actual = null;
            try { actual = QualifierGameplayObserver.ReadMap(fromRoom ? _room.SelectedBeatmap.Key : _detail.beatmapKey); } catch (Exception) { }
            return (fromRoom ? _room.SelectionReady : IsSoloSelection) && Equals(context.Map, actual) && _previous != null && context.OwnerSid == _identity.CurrentSid
                && context.LeagueId == _previous.LeagueId && Equals(context.Map, _previous.Map)
                && Replay.ReplayModeDetector.BlockingReason() == null
                && _runtime.IsSubmissionAllowed(out _);
        }
        internal System.Threading.Tasks.Task<bool> StartAsync(ChallengeContext context) => _play.StartAsync(context);
        internal System.Threading.Tasks.Task StartPracticeAsync() => _direct.StartPracticeAsync();
        public void ApplyLock()
        {
            _room.ApplyLock();
            if (!Locked) { RestoreGroups(); return; }
            // Lock song list, difficulty, characteristic, Play/Practice and modifiers.
            LockRoot(_solo.topViewController as LevelSelectionNavigationController);
            if (!_room.IsOpen) LockRoot(_setup);
        }
        private void LockRoot(Component root)
        {
            if (root == null) return;
            var group = root.GetComponent<CanvasGroup>() ?? root.gameObject.AddComponent<CanvasGroup>();
            if (!_groups.ContainsKey(group)) _groups.Add(group, Tuple.Create(group.interactable, group.blocksRaycasts));
            group.interactable = false;
            group.blocksRaycasts = false;
        }
        private void RestoreGroups()
        {
            foreach (var pair in _groups)
                if (pair.Key != null) { pair.Key.interactable = pair.Value.Item1; pair.Key.blocksRaycasts = pair.Value.Item2; }
            _groups.Clear();
        }
        public void Dispose()
        {
            _detail.didChangeDifficultyBeatmapEvent -= DifficultyChanged;
            _detail.didChangeContentEvent -= ContentChanged;
            _leaderboard.Updated -= BoardUpdated;
            _identity.Changed -= SelectionUpdated;
            RestoreGroups();
            _runtime.DetachMenu(this);
            if (Instance == this) Instance = null;
        }
    }

    [HarmonyPatch(typeof(SinglePlayerLevelSelectionFlowCoordinator), "BackButtonWasPressed")]
    internal static class QualifierBackLockPatch
    {
        private static bool Prefix()
        {
            var menu = QualifierMenuController.Instance;
            if (menu?.CancelPendingLaunch() == true) return false;
            return menu?.Locked != true;
        }
    }
    [HarmonyPatch(typeof(SinglePlayerLevelSelectionFlowCoordinator), "ActionButtonWasPressed")]
    internal static class QualifierPlayLockPatch
    {
        private static bool Prefix()
        {
            var menu = QualifierMenuController.Instance;
            if (menu?.Locked == true && !menu.Invoking) return false;
            if (menu?.Invoking != true) QualifierRuntime.Instance?.OrdinaryPlayRequested();
            return true;
        }
    }
    [HarmonyPatch(typeof(SinglePlayerLevelSelectionFlowCoordinator), "PracticeButtonWasPressed")]
    internal static class QualifierPracticeLockPatch
    {
        private static bool Prefix()
        {
            if (QualifierMenuController.Instance?.Locked == true) return false;
            QualifierRuntime.Instance?.OrdinaryPlayRequested();
            return true;
        }
    }
}

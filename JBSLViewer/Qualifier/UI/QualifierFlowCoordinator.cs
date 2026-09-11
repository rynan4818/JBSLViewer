/*
Portions copied/adapted from TournamentAssistant.
Source: https://github.com/MatrikMoon/TournamentAssistant?tab=MIT-1-ov-file
Original: TournamentAssistant/UI/FlowCoordinators/QualifierCoordinator.cs; TournamentAssistant/UI/FlowCoordinators/EventSelectionCoordinator.cs
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
#pragma warning disable CS0649 // These fields are assigned by Zenject.
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using BeatSaberMarkupLanguage;
using HMUI;
using IPA.Utilities;
using JBSLViewer.Models;
using JBSLViewer.Views;
using JBSLViewer.Qualifier.Core.Contracts;
using UnityEngine;
using Zenject;

namespace JBSLViewer.Qualifier.UI
{
    public sealed class QualifierFlowCoordinator : FlowCoordinator
    {
        [Inject] private ActiveLeague _activeLeagues;
        [Inject] private Leaderboard _boards;
        [Inject] private BeatmapLevelsModel _levels;
        [Inject] private BeatmapDataLoader _beatmapDataLoader;
        [Inject] private GameplaySetupViewController _setup;
        [Inject] private QualifierRuntime _runtime;
        [Inject] private QualifierRoomState _room;
        [Inject] private PlayerIdentityService _identity;
        [Inject] private QualifierDispatcher _dispatcher;
        [Inject] private LatestUpdate _latest;
        [Inject] private DiContainer _container;
        [Inject] private VirtualLeagueService _virtualLeagues;
        [Inject] private SoloFreePlayFlowCoordinator _solo;
        [Inject] private PlayerDataModel _player;
        public event Action ExitRequested;
        public QualifierBeatmap SelectedBeatmap { get; private set; }
        public bool HasSelectedSong => isActivated && topViewController == _detail && SelectedBeatmap != null;
        private QualifierLeagueSelectionViewController _leagues;
        private QualifierSongSelectionViewController _songs;
        private QualifierSongDetailViewController _detail;
        private LeaderboardMainViewController _ranking;
        private QualifierStatusViewController _status;
        private ResultsViewController _results;
        private QualifierDirectPlayResult _displayedResult;
        private bool _resultsClosing;
        private CancellationTokenSource _songLoading;
        private readonly List<ViewController> _owned = new List<ViewController>();
        private CanvasGroup _setupLock;
        private bool _savedInteractable, _savedRaycasts;
        private bool _listBusy, _refreshing, _retrying, _leaving, _rankingShown;
        private float _nextRefresh;

        private T Create<T>() where T : ViewController
        {
            var view = BeatSaberUI.CreateViewController<T>();
            _owned.Add(view);
            return view;
        }
        public override void DidActivate(bool firstActivation, bool addedToHierarchy, bool screenSystemEnabling)
        {
            if (firstActivation)
            {
                _leagues = Create<QualifierLeagueSelectionViewController>();
                _songs = Create<QualifierSongSelectionViewController>();
                _detail = Create<QualifierSongDetailViewController>();
                _ranking = Create<LeaderboardMainViewController>();
                _container.Inject(_ranking);
                _status = Create<QualifierStatusViewController>();
                _leagues.ItemSelected += id => { _room.LeagueIndex = _leagues.SelectedIndex; _room.SongIndex = 0; Observe(SelectLeagueAsync(id)); };
                _leagues.ReloadRequested += () => Observe(LoadLeaguesAsync(true));
                _songs.SongSelected += item => Observe(SelectSongAsync(item));
                _songs.ReloadRequested += () => Observe(SelectLeagueAsync(_room.LeagueId, reload: true));
                _detail.ChallengePressed += Challenge;
                _detail.ConfirmPressed += () => Observe(ConfirmAsync());
                _detail.CancelPressed += () => { _runtime.CancelConfirmation(); Render(); };
                _detail.PracticePressed += () => Observe(QualifierMenuController.Instance?.StartPracticeAsync() ?? Task.CompletedTask);
                _status.RetryRequested += () => Observe(RetryAsync());
                _runtime.StateChanged += Render;
                _boards.Updated += BoardUpdated;
                _virtualLeagues.VirtualLeaderboardUpdated += BoardUpdated;
                _identity.Changed += IdentityChanged;
            }
            if (addedToHierarchy)
            {
                SetTitle("JBSL CHALLENGE", ViewController.AnimationType.None);
                showBackButton = true;
                ProvideInitialViewControllers(_leagues);
            }
            if (!firstActivation && screenSystemEnabling)
                QualifierMenuController.Instance?.DirectMenuActivated();
        }
        public override void InitialViewControllerWasPresented()
        {
            base.InitialViewControllerWasPresented();
            Observe(LoadLeaguesAsync(false));
        }
        private async void Observe(Task action)
        {
            try { await action; }
            catch (OperationCanceledException) { }
            catch (Exception ex)
            {
                Plugin.Log.Error("Challenge room failed: " + ex);
                if (!_leaving) { _room.Notice = "Could not load this screen. Use RELOAD to try again."; Render(); }
            }
        }
        private async Task LoadLeaguesAsync(bool reload)
        {
            if (_listBusy || _leaving || _runtime.SelectionLocked) return;
            _listBusy = true;
            _leagues.SetBusy(true);
            var generation = _room.Generation;
            try
            {
                _leagues.SetStatus("Loading leagues...");
                if (reload || _activeLeagues._leagues == null) await _activeLeagues.GetActiveLeagueAsync();
                if (!_room.IsCurrent(generation) || _leaving) return;
                _leagues.SetItems(_activeLeagues._leagues);
                _leagues.SetStatus(_activeLeagues._leagues?.Count > 0 ? "Select a league" : "No leagues available. RELOAD to try again.");
            }
            finally { _listBusy = false; _leagues.SetBusy(false); }
            if (_room.IsCurrent(generation) && _room.LeagueId > 0)
                await SelectLeagueAsync(_room.LeagueId, _room.Map, true);
        }
        private async Task SelectLeagueAsync(int leagueId, MapKey selectedMap = null, bool reload = false)
        {
            if (_leaving || _runtime.SelectionLocked || _listBusy || _leagues.NoticeShown) return;
            _listBusy = true;
            _leagues.SetBusy(true);
            var notice = _room.Notice;
            var generation = _room.Select(leagueId, null);
            _songLoading?.Cancel();
            SelectedBeatmap = null;
            QualifierMenuController.Instance?.SelectionUpdated();
            HidePanels();
            if (topViewController == _detail) DismissViewController(_detail, immediately: true);
            _leagues.SetStatus("Loading challenge maps...");
            _songs.SetStatus("Loading challenge maps...");
            try
            {
                if (string.IsNullOrWhiteSpace(_identity.CurrentSid)) await _identity.RefreshAsync();
                if (!_room.IsCurrent(generation) || _leaving) return;
                var requestedSid = _identity.CurrentSid;
                await _boards.GetLeaderboardAsync(leagueId, reload);
                if (!_room.IsCurrent(generation) || _leaving) return;
                var board = _boards.GetLeaderboardData(leagueId);
                var problem = QualifierScreenData.LeagueEntryProblem(board?.qualifierContract, leagueId,
                    _boards.IsQualifierCacheFresh(leagueId), requestedSid, _identity.CurrentSid);
                if (problem != null)
                {
                    if (topViewController == _songs) DismissViewController(_songs, immediately: true);
                    _room.Select(0, null);
                    _leagues.SetStatus("Select a league");
                    _leagues.RestorePosition(_room.LeagueIndex);
                    var name = board?.qualifierContract?.Title ?? _activeLeagues._leagues?.FirstOrDefault(l => l.id == leagueId)?.name ?? "League " + leagueId;
                    _leagues.ShowNotice(problem.Title, name, problem.Message);
                    QualifierMenuController.Instance?.SelectionUpdated();
                    return;
                }
                var rows = board.qualifierContract.Maps.Select(map => new QualifierSongListItem(map, FindPreview(map.Key))).ToList();
                _songs.SetSongs(rows);
                _songs.SetStatus(board.qualifierContract.Title + " - select a map");
                if (topViewController != _songs) PresentViewController(_songs, immediately: true);
                ShowRanking();
                if (selectedMap != null)
                {
                    var selected = rows.FirstOrDefault(x => x.Map.Key.Equals(selectedMap));
                    _listBusy = false;
                    if (selected != null) await SelectSongAsync(selected);
                }
                _room.Notice = notice;
                Render();
            }
            finally { _listBusy = false; _leagues.SetBusy(false); }
        }
        private BeatmapLevel FindPreview(MapKey key)
        {
            var id = "custom_level_" + key.Hash;
            return _levels.GetBeatmapLevel(id);
        }
        private async Task SelectSongAsync(QualifierSongListItem item)
        {
            if (_leaving || _runtime.SelectionLocked || item == null) return;
            _songLoading?.Cancel(); _songLoading?.Dispose();
            _songLoading = new CancellationTokenSource();
            var token = _songLoading.Token;
            _room.SongIndex = Math.Max(0, _songs.IndexOf(item));
            var generation = _room.Select(_room.LeagueId, item.Map.Key);
            SelectedBeatmap = null;
            QualifierMenuController.Instance?.SelectionUpdated();
            if (item.Level == null) { _songs.SetStatus("Map not installed. Install it, then RELOAD."); return; }
            _songs.SetStatus("Loading " + (item.Level.songName ?? item.Map.Title) + "...");
            var level = item.Level;
            var key = level.GetBeatmapKeys().FirstOrDefault(k => k.beatmapCharacteristic.serializedName == item.Map.Characteristic
                && k.difficulty.ToString() == item.Map.Key.Difficulty);
            if (!key.IsValid()) { _songs.SetStatus("Could not find the specified difficulty. RELOAD to try again."); return; }
            var result = await _levels.LoadBeatmapLevelDataAsync(level.levelID, BeatmapLevelDataVersion.Original, token);
            if (!_room.IsCurrent(generation) || token.IsCancellationRequested || _leaving) return;
            var data = result.beatmapLevelData;
            if (result.isError || data == null || !data.ContainsBeatmapData(key))
            {
                item.SetError("Could not load the specified difficulty");
                _songs.SetStatus("Map unavailable. RELOAD to try again.");
                return;
            }
            var basicInfo = await _beatmapDataLoader.LoadBasicBeatmapDataAsync(data, key);
            if (!_room.IsCurrent(generation) || token.IsCancellationRequested || _leaving) return;
            if (basicInfo == null)
            {
                item.SetError("Could not read the specified difficulty");
                _songs.SetStatus("Map unavailable. RELOAD to try again.");
                return;
            }
            var map = new QualifierBeatmap(key, level, data, basicInfo);
            SelectedBeatmap = map;
            _detail.SetSong(map);
            _setup.Setup(true, true, true, false, PlayerSettingsPanelController.PlayerSettingsPanelLayout.Singleplayer);
            PresentViewController(_detail, immediately: true);
            SetLeftScreenViewController(_setup, ViewController.AnimationType.In);
            ShowRanking();
            SetBottomScreenViewController(_status, ViewController.AnimationType.In);
            QualifierMenuController.Instance?.SelectionUpdated();
            Render();
        }
        private void BoardUpdated(int league)
        {
            if (league == _room.LeagueId) _dispatcher.Post(() =>
            {
                if (_leaving || league != _room.LeagueId) return;
                QualifierMenuController.Instance?.SelectionUpdated();
                RenderRanking(); Render();
            });
        }
        private void IdentityChanged() => _dispatcher.Post(() => { if (!_leaving) { RenderRanking(); Render(); } });
        private async Task RefreshBoardAsync(bool force)
        {
            if (_refreshing || _leaving || _runtime.SelectionLocked || _room.LeagueId <= 0) return;
            _refreshing = true;
            try { await _boards.GetLeaderboardAsync(_room.LeagueId, force); }
            finally { _refreshing = false; }
        }
        private void Update()
        {
            if (!isActivated || _leaving || Time.unscaledTime < _nextRefresh) return;
            _nextRefresh = Time.unscaledTime + 1;
            _latest.RefrashLatest();
            if (_room.LeagueId > 0 && !_boards.IsQualifierCacheFresh(_room.LeagueId)) Observe(RefreshBoardAsync(false));
            Render();
        }
        private void ShowRanking()
        {
            if (_leaving || _room.LeagueId <= 0) return;
            _rankingShown = true;
            RenderRanking();
            SetRightScreenViewController(_ranking, ViewController.AnimationType.In);
        }
        private void RenderRanking()
        {
            if (_ranking == null || !_rankingShown || _leaving || _room.LeagueId <= 0) return;
            var board = _boards.GetLeaderboardData(_room.LeagueId);
            // Selecting a row fills Room.Map before its async load completes.
            // Keep TOTAL visible until the detail view has actually been presented.
            if (topViewController == _songs)
            {
                var name = board?.qualifierContract?.Title
                    ?? _activeLeagues._leagues?.FirstOrDefault(l => l.id == _room.LeagueId)?.name ?? "League " + _room.LeagueId;
                _ranking.SetDisplayTotal(_room.LeagueId, name + " - TOTAL", _identity.CurrentSid);
                return;
            }
            if (topViewController != _detail || _room.Map == null) return;
            var map = QualifierScreenData.FindRankingMap(board, _room.Map);
            _ranking.SetDisplaySelection(_room.LeagueId, _room.Map, map?.title ?? SelectedBeatmap?.Level.songName ?? "JBSL CHALLENGE", _identity.CurrentSid);
        }
        public void Render()
        {
            if (_leaving || _detail == null) return;
            var state = _runtime.ViewState;
            var replay = Replay.ReplayModeDetector.BlockingReason();
            var message = _runtime.ConfigurationMessage ?? _room.Notice ?? _runtime.Notice
                ?? (replay == null ? null : "Challenge unavailable: " + replay)
                ?? QualifierScreenData.SelectionProblem(_runtime.CaptureSelection(), DateTimeOffset.UtcNow)
                ?? state.Message;
            _detail.SetState(state, _runtime.ConfigurationMessage == null, !_room.LaunchPending, _runtime.SelectionLocked || _room.LaunchPending);
            _status.SetState(state.RemainingAttempts, state.AttemptLimit, message, _runtime.SelectionLocked || _room.LaunchPending || _retrying);
            showBackButton = QualifierMenuController.Instance?.PreparingDirectPlay == true
                || (!_runtime.SelectionLocked && !_room.LaunchPending);
            ApplyLock();
        }
        public void ApplyLock()
        {
            if ((_runtime.SelectionLocked || _room.LaunchPending) && HasSelectedSong)
            {
                if (_setupLock == null)
                {
                    _setupLock = _setup.GetComponent<CanvasGroup>() ?? _setup.gameObject.AddComponent<CanvasGroup>();
                    _savedInteractable = _setupLock.interactable; _savedRaycasts = _setupLock.blocksRaycasts;
                }
                _setupLock.interactable = _setupLock.blocksRaycasts = false;
            }
            else RestoreSetup();
        }
        private void RestoreSetup()
        {
            if (_setupLock == null) return;
            _setupLock.interactable = _savedInteractable; _setupLock.blocksRaycasts = _savedRaycasts; _setupLock = null;
        }
        private void Challenge()
        {
            if (!HasSelectedSong || _room.LaunchPending) return;
            QualifierMenuController.Instance?.SelectionUpdated();
            if (!_runtime.BeginConfirmation()) { Render(); return; }
            _detail.ShowConfirmation(_runtime.CaptureSelection(), _runtime.ViewState.RemainingAttempts);
            Render();
        }
        private async Task ConfirmAsync() { await _runtime.ConfirmAsync(); Render(); }
        private async Task RetryAsync()
        {
            if (_runtime.SelectionLocked || _retrying) return;
            _retrying = true; _room.Notice = null; Render();
            try { await _runtime.RetryManuallyAsync(); await RefreshBoardAsync(true); }
            finally { _retrying = false; Render(); }
        }
        public void ShowDirectResult(QualifierDirectPlayResult result)
        {
            if (_leaving || result == null) return;
            _room.Notice = result.Notice;
            _displayedResult = result;
            if (!result.ShowResults || result.TransformedBeatmap == null || result.Beatmap == null)
            {
                _room.Resume();
                _displayedResult = null;
                RestoreAfterPlay();
                return;
            }
            if (_results == null)
            {
                var template = _solo.GetField<ResultsViewController, SoloFreePlayFlowCoordinator>("_resultsViewController");
                // Clone the native UI, not Solo's event ownership. Unity does not
                // serialize the C# delegate fields or HMUI's runtime button binder.
                _results = _container.InstantiatePrefabForComponent<ResultsViewController>(template.gameObject);
                _results.name = "JBSLChallengeResults";
                _results.gameObject.SetActive(false);
                _owned.Add(_results);
            }
            UnbindResultEvents();
            var map = result.Beatmap;
            var key = map.Key;
            var stats = _player.playerData.TryGetPlayerLevelStatsData(in key);
            _results.Init(result.Completion, result.TransformedBeatmap, in key, map.Level, false,
                stats == null || stats.highScore < result.Completion.modifiedScore);
            _results.GetField<UnityEngine.UI.Button, ResultsViewController>("_restartButton").gameObject.SetActive(result.Practice);
            _results.continueButtonPressedEvent += ResultContinue;
            _results.restartButtonPressedEvent += ResultRestart;
            SetResultLights(result.Completion.levelEndStateType == LevelCompletionResults.LevelEndStateType.Cleared
                ? "_resultsClearedLightsPreset" : "_resultsFailedLightsPreset");
            PresentViewController(_results, immediately: true);
            QualifierMenuController.Instance?.SelectionUpdated();
            Render();
        }
        private void ResultContinue(ResultsViewController view) { if (view == _results) CloseResults(false); }
        public void RecoverAfterResultFailure()
        {
            UnbindResultEvents();
            _displayedResult = null;
            _resultsClosing = false;
            if (_results != null && topViewController == _results) DismissViewController(_results, immediately: true);
            _room.Resume();
            _room.Notice = "Could not display the result. Check the challenge result status.";
            RestoreAfterPlay();
        }
        private void ResultRestart(ResultsViewController view)
        { if (view == _results && _displayedResult?.Practice == true) CloseResults(true); }
        private void UnbindResultEvents()
        {
            if (_results == null) return;
            _results.continueButtonPressedEvent -= ResultContinue;
            _results.restartButtonPressedEvent -= ResultRestart;
        }
        private void CloseResults(bool practiceAgain)
        {
            if (_leaving || _resultsClosing || topViewController != _results || _displayedResult == null) return;
            _resultsClosing = true;
            UnbindResultEvents();
            _displayedResult = null;
            _room.Resume();
            var generation = _room.Generation;
            SetResultLights("_defaultLightsPreset");
            DismissViewController(_results, finishedCallback: () =>
            {
                _resultsClosing = false;
                if (_leaving || !_room.IsCurrent(generation) || topViewController != _detail) return;
                RestoreAfterPlay();
                if (practiceAgain) Observe(QualifierMenuController.Instance?.StartPracticeAsync() ?? Task.CompletedTask);
            });
        }
        private void SetResultLights(string preset)
        {
            var lights = _solo.GetField<MenuLightsManager, SoloFreePlayFlowCoordinator>("_menuLightsManager");
            var color = preset == "_resultsClearedLightsPreset"
                ? _solo.GetField<MenuLightsPresetSO, SoloFreePlayFlowCoordinator>("_resultsClearedLightsPreset")
                : preset == "_resultsFailedLightsPreset"
                    ? _solo.GetField<MenuLightsPresetSO, SoloFreePlayFlowCoordinator>("_resultsFailedLightsPreset")
                    : _solo.GetField<MenuLightsPresetSO, SoloFreePlayFlowCoordinator>("_defaultLightsPreset");
            if (lights != null && color != null) lights.SetColorPreset(color, true);
        }
        private void RestoreAfterPlay()
        {
            SetResultLights("_defaultLightsPreset");
            QualifierMenuController.Instance?.SelectionUpdated();
            RenderRanking();
            Render();
            Observe(RefreshBoardAsync(true));
        }
        private void HidePanels(bool keepRanking = false)
        {
            RestoreSetup();
            SetLeftScreenViewController(null, ViewController.AnimationType.Out);
            if (!keepRanking)
            {
                _rankingShown = false;
                SetRightScreenViewController(null, ViewController.AnimationType.Out);
            }
            SetBottomScreenViewController(null, ViewController.AnimationType.Out);
        }
        public override void BackButtonWasPressed(ViewController viewController)
        {
            if (_leaving || _resultsClosing) return;
            if (QualifierMenuController.Instance?.CancelPendingLaunch() == true) { Render(); return; }
            if (_runtime.SelectionLocked || _room.LaunchPending) return;
            if (topViewController == _results) { CloseResults(false); return; }
            if (_leagues.HideNotice()) return;
            _songLoading?.Cancel();
            if (topViewController == _detail)
            {
                SelectedBeatmap = null;
                var generation = _room.Select(_room.LeagueId, null);
                HidePanels(keepRanking: true);
                DismissViewController(_detail, finishedCallback: () =>
                {
                    if (_leaving || !_room.IsCurrent(generation) || topViewController != _songs) return;
                    _songs.RestorePosition(_room.SongIndex);
                    ShowRanking();
                });
            }
            else if (topViewController == _songs)
            {
                var generation = _room.Select(0, null);
                HidePanels();
                DismissViewController(_songs, finishedCallback: () =>
                {
                    if (!_leaving && _room.IsCurrent(generation)) _leagues.RestorePosition(_room.LeagueIndex);
                });
                _leagues.SetStatus("Select a league");
            }
            else ExitRequested?.Invoke();
            QualifierMenuController.Instance?.SelectionUpdated();
        }
        public void PrepareForDismiss()
        {
            _leaving = true;
            UnbindResultEvents();
            if (_displayedResult != null) SetResultLights("_defaultLightsPreset");
            _displayedResult = null;
            _songLoading?.Cancel();
            _detail?.HideConfirmation();
            _leagues?.HideNotice();
            HidePanels();
            while (topViewController != null && topViewController != _leagues)
                DismissViewController(topViewController, immediately: true);
        }
        private void OnDestroy()
        {
            _leaving = true;
            UnbindResultEvents();
            _songLoading?.Cancel(); _songLoading?.Dispose();
            RestoreSetup();
            if (_runtime != null) _runtime.StateChanged -= Render;
            if (_boards != null) _boards.Updated -= BoardUpdated;
            if (_virtualLeagues != null) _virtualLeagues.VirtualLeaderboardUpdated -= BoardUpdated;
            if (_identity != null) _identity.Changed -= IdentityChanged;
            foreach (var view in _owned) if (view != null) UnityEngine.Object.Destroy(view.gameObject);
            _owned.Clear();
        }
    }
}

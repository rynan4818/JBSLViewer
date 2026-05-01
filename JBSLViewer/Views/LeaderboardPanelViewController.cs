using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.UI;
using TMPro;
using HMUI;
using Zenject;
using SiraUtil.Zenject;
using BeatSaberMarkupLanguage.Attributes;
using BeatSaberMarkupLanguage.Components.Settings;
using BeatSaberMarkupLanguage.ViewControllers;
using JBSLViewer.Configuration;
using JBSLViewer.Models;

namespace JBSLViewer.Views
{
    [HotReload]
    public class LeaderboardPanelViewController : BSMLAutomaticViewController, IAsyncInitializable, ITickable
    {
        private const string PlaceholderLeagueId = "-1";
        private const string PlaceholderLeaderboardId = "-1";
        private const string LoadingLeagueText = "Loading leagues...";
        private const string LoadingLeaderboardText = "Loading leaderboards...";
        private const string NoLeagueDataText = "No league data";
        private const string NoLeaderboardDataText = "No leaderboard data";

        public bool _init = false;
        public float _currentCycleTime = 0f;
        public static SemaphoreSlim AllResetSemaphore = new SemaphoreSlim(1, 1);
        public static SemaphoreSlim SetLeaderboardSemaphore = new SemaphoreSlim(1, 1);
        public static SemaphoreSlim LeaderboardInfoSemaphore = new SemaphoreSlim(1, 1);

        private bool _suppressLeagueSelectionChanged = false;
        private bool _suppressLeaderboardSelectionChanged = false;
        private bool _suppressVirtualParticipationChanged = false;
        private bool _isLeagueLoading = true;
        private bool _isLeaderboardLoading = true;
        private bool _isVirtualParticipationLoading = false;
        private bool _virtualEventsSubscribed = false;
        private bool _virtualParticipationEnabled = false;
        private bool _virtualProgressActive = false;
        private int _virtualProgressLeagueId = -1;
        private int _virtualProgressCompleted = 0;
        private int _virtualProgressTotal = 0;

        [Inject]
        private readonly ActiveLeague _activeLeague;
        [Inject]
        private readonly Leaderboard _leaderboard;
        [Inject]
        private readonly LatestUpdate _latestUpdate;
        [Inject]
        private readonly LeaderboardInfo _leaderboardInfo;
        [Inject]
        private readonly LeaderboardMainViewController _leaderboardMainViewController;
        [Inject]
        private readonly VirtualLeagueService _virtualLeagueService;

        public async Task InitializeAsync(CancellationToken token)
        {
            this.EnsureVirtualLeagueEventSubscription();
            await this.AllResetAsync();
        }

        public void Tick()
        {
            if (!this.isActivated || !this._init)
                return;
            if (this._currentCycleTime < 1f)
            {
                this._currentCycleTime += Time.deltaTime;
                return;
            }
            this._currentCycleTime = 0f;
            this._latestUpdate.RefrashLatest();
            this.RfreshTimeUpdate();
            if (this._leaderboardMainViewController.TryRefreshCurrentUserSid())
                this._leaderboardMainViewController.SetRecords();
            if (this._virtualLeagueService.TryRefreshCurrentUser())
            {
                this.SyncVirtualParticipationValue();
                this.UpdateControlInteractivity();
            }
            if (LeaderboardInfoSemaphore.CurrentCount == 0 || AllResetSemaphore.CurrentCount == 0 || SetLeaderboardSemaphore.CurrentCount == 0)
                return;
            if (!int.TryParse(this._jbslLeagueValue, out var leagueID) || leagueID == -1)
                return;
            if (this._leaderboard._leaderboards.ContainsKey(leagueID) && this._latestUpdate._latest > this._leaderboard._leaderboards[leagueID].jbslViewerGetTime)
                _ = this.SetLeaderboardsAsync(this._leaderboardValue, true);
        }

        public async Task AllResetAsync()
        {
            this._isLeagueLoading = true;
            this._isLeaderboardLoading = true;
            this.SetChoices(this.JBSLLeagueChoices, null, PlaceholderLeagueId);
            this.SetChoices(this.LeaderboardChoices, null, PlaceholderLeaderboardId);
            this.SetLeagueValueInternal(PlaceholderLeagueId);
            this.SetLeaderboardValueInternal(PlaceholderLeaderboardId);
            if (this._init)
            {
                this.RefreshLeagueDropdown();
                this.RefreshLeaderboardDropdown();
                this.UpdateControlInteractivity();
            }

            await AllResetSemaphore.WaitAsync();
            try
            {
                this._leaderboardMainViewController.SetTitle("");
                await this._latestUpdate.GetHeadlineAsync();
                await this._activeLeague.GetActiveLeagueAsync();
                if (this._activeLeague._leagues == null || this._activeLeague._leagues.Count <= 0)
                    return;

                var leagueChoices = new List<object>();
                foreach (var league in this._activeLeague._leagues)
                    leagueChoices.Add(league.id.ToString());
                this.SetChoices(this.JBSLLeagueChoices, leagueChoices, PlaceholderLeagueId);

                if (this._activeLeague.GetLeagueIndex(PluginConfig.Instance.selectLeagueID) == -1)
                    PluginConfig.Instance.selectLeagueID = this._activeLeague._leagues[0].id;
                this.SetLeagueValueInternal(PluginConfig.Instance.selectLeagueID.ToString());
                this.SyncVirtualParticipationValue();
                if (this._init)
                    this.RefreshLeagueDropdown();
            }
            finally
            {
                this._isLeagueLoading = false;
                AllResetSemaphore.Release();
                if (this._init)
                {
                    this.RefreshLeagueDropdown();
                    this.RefreshLeaderboardDropdown();
                    this.UpdateControlInteractivity();
                }
            }

            await this.SetLeaderboardsAsync();
        }

        public async Task SetLeaderboardsAsync(string indexString = "0", bool reload = false)
        {
            var leagueID = -1;
            string resolvedIndexString = PlaceholderLeaderboardId;
            this._isLeaderboardLoading = true;
            this.SetChoices(this.LeaderboardChoices, null, PlaceholderLeaderboardId);
            this.SetLeaderboardValueInternal(PlaceholderLeaderboardId);
            if (this._init)
            {
                this.RefreshLeaderboardDropdown();
                this.UpdateControlInteractivity();
            }

            await SetLeaderboardSemaphore.WaitAsync();
            try
            {
                if (!int.TryParse(this._jbslLeagueValue, out leagueID) || leagueID == -1)
                    return;
                if (this._activeLeague.GetLeagueIndex(leagueID) == -1)
                    return;

                PluginConfig.Instance.selectLeagueID = leagueID;
                this._leaderboardMainViewController.SetTitle("");
                await this._leaderboard.GetLeaderboardAsync(leagueID, reload);
                if (!this._leaderboard._leaderboards.ContainsKey(leagueID))
                    return;

                var leaderboard = this._leaderboard._leaderboards[leagueID];
                if (leaderboard == null || leaderboard.maps == null)
                    return;

                var leaderboardChoices = new List<object>();
                for (var i = 0; i <= leaderboard.maps.Count; i++)
                    leaderboardChoices.Add(i.ToString());
                this.SetChoices(this.LeaderboardChoices, leaderboardChoices, PlaceholderLeaderboardId);
                this._virtualLeagueService.SyncLeagueParticipationState(leagueID);
                if (!this.LeaderboardChoices.Contains(indexString))
                    indexString = this.LeaderboardChoices.Contains("0") ? "0" : this.LeaderboardChoices[0] as string;
                resolvedIndexString = indexString;
            }
            finally
            {
                this._isLeaderboardLoading = false;
                SetLeaderboardSemaphore.Release();
                if (this._init)
                {
                    this.RefreshLeaderboardDropdown();
                    this.UpdateControlInteractivity();
                }
            }

            if (!string.Equals(resolvedIndexString, PlaceholderLeaderboardId, StringComparison.Ordinal))
            {
                this.SetLeaderboardValueInternal(resolvedIndexString);
                if (this._init)
                {
                    this.RefreshLeaderboardDropdown();
                    this.UpdateControlInteractivity();
                }
            }

            if (leagueID == -1 || this.IsPlaceholderOnly(this.LeaderboardChoices, PlaceholderLeaderboardId))
                return;

            await LeaderboardInfoSemaphore.WaitAsync();
            try
            {
                await this._leaderboardInfo.SetLeagueMapDataAsync(leagueID);
            }
            finally
            {
                LeaderboardInfoSemaphore.Release();
                if (this._init)
                    this.UpdateControlInteractivity();
            }

            this.SyncVirtualParticipationValue();
            if (this._init)
                this.UpdateControlInteractivity();
        }

        public async Task LeagueReloadAsync()
        {
            this._isLeagueLoading = true;
            this._isLeaderboardLoading = true;
            this.SetChoices(this.JBSLLeagueChoices, null, PlaceholderLeagueId);
            this.SetChoices(this.LeaderboardChoices, null, PlaceholderLeaderboardId);
            this.SetLeagueValueInternal(PlaceholderLeagueId);
            this.SetLeaderboardValueInternal(PlaceholderLeaderboardId);
            if (this._init)
            {
                this.RefreshLeagueDropdown();
                this.RefreshLeaderboardDropdown();
                this.UpdateControlInteractivity();
            }

            await this.AllResetAsync();
        }

        public void RfreshTimeUpdate()
        {
            if (!this._init)
                return;

            if (this._virtualProgressActive &&
                int.TryParse(this._jbslLeagueValue, out var currentLeagueId) &&
                currentLeagueId == this._virtualProgressLeagueId)
            {
                this._autoReloadTimer.text = $"Loading Virtual Scores {this._virtualProgressCompleted} / {this._virtualProgressTotal}";
                return;
            }

            var time = (this._latestUpdate._latest + TimeSpan.FromMinutes(PluginConfig.Instance.refreshInterval) - DateTime.Now).ToString(@"mm\:ss");
            this._autoReloadTimer.text = $"Auto Reload Timer {time}";
        }

        public string GetLeaderboardName()
        {
            if (!this._init)
                return "";
            return this.LeaderboardFormat(this._leaderboardValue);
        }

        public void SetLeaderboard(string indexString)
        {
            if (AllResetSemaphore.CurrentCount == 0 || SetLeaderboardSemaphore.CurrentCount == 0)
                return;
            if (!this.LeaderboardChoices.Contains(indexString))
                return;
            this.LeaderboardValue = indexString;
            if (this._init)
                this.NotifyPropertyChanged("LeaderboardValue");
        }

        [UIComponent("JBSLLeagueID")]
        private readonly DropDownListSetting _jbslLeagueSetting;

        [UIComponent("JBSLLeagueID")]
        private readonly RectTransform _jbslLeagueTransform;

        [UIComponent("LeaderboardID")]
        private readonly DropDownListSetting _leaderboardSetting;

        [UIComponent("LeaderboardID")]
        private readonly RectTransform _leaderboardTransform;

        [UIComponent("AutoReloadTimer")]
        private readonly TextMeshProUGUI _autoReloadTimer;

        [UIComponent("LeagueReloadButton")]
        private readonly Button _leagueReloadButton;

        [UIComponent("ReloadButton")]
        private readonly Button _reloadButton;

        [UIComponent("TotalButton")]
        private readonly Button _totalButton;

        [UIComponent("VirtualParticipationToggle")]
        private readonly ToggleSetting _virtualParticipationSetting;

        [UIComponent("VirtualParticipationToggle")]
        private readonly RectTransform _virtualParticipationTransform;

        [UIValue("JBSLLeagueChoices")]
        public List<object> JBSLLeagueChoices { get; set; } = new List<object> { PlaceholderLeagueId };

        [UIValue("LeaderboardChoices")]
        public List<object> LeaderboardChoices { get; set; } = new List<object> { PlaceholderLeaderboardId };

        private string _jbslLeagueValue = PlaceholderLeagueId;
        [UIValue("JBSLLeagueValue")]
        public string JBSLLeagueValue
        {
            get => this._jbslLeagueValue;
            set
            {
                value = string.IsNullOrEmpty(value) ? PlaceholderLeagueId : value;
                if (string.Equals(this._jbslLeagueValue, value, StringComparison.Ordinal))
                    return;

                this._jbslLeagueValue = value;
                this.SyncVirtualParticipationValue();
                if (this._init)
                    this.UpdateControlInteractivity();
                if (this._suppressLeagueSelectionChanged || value == PlaceholderLeagueId)
                    return;
                if (LeaderboardInfoSemaphore.CurrentCount == 0 || AllResetSemaphore.CurrentCount == 0 || SetLeaderboardSemaphore.CurrentCount == 0)
                    return;
                _ = this.SetLeaderboardsAsync();
            }
        }

        private string _leaderboardValue = PlaceholderLeaderboardId;
        [UIValue("LeaderboardValue")]
        public string LeaderboardValue
        {
            get => this._leaderboardValue;
            set
            {
                value = string.IsNullOrEmpty(value) ? PlaceholderLeaderboardId : value;
                this._leaderboardValue = value;
                if (this._suppressLeaderboardSelectionChanged)
                    return;

                if (value == PlaceholderLeaderboardId)
                    this._leaderboardMainViewController.SetTitle("");
                else
                    this._leaderboardMainViewController.SetTitle(this.LeaderboardFormat(value));
            }
        }

        [UIValue("VirtualParticipationEnabled")]
        public bool VirtualParticipationEnabled
        {
            get => this._virtualParticipationEnabled;
            set
            {
                if (this._suppressVirtualParticipationChanged || this._virtualParticipationEnabled == value)
                    return;

                this._virtualParticipationEnabled = value;
                _ = this.SetVirtualParticipationEnabledAsync(value);
            }
        }

        [UIAction("Total")]
        public void Total()
        {
            this.SetLeaderboard("0");
        }

        [UIAction("Reload")]
        public void Reload()
        {
            if (LeaderboardInfoSemaphore.CurrentCount == 0 || AllResetSemaphore.CurrentCount == 0 || SetLeaderboardSemaphore.CurrentCount == 0)
                return;
            _ = this.SetLeaderboardsAsync(this._leaderboardValue, true);
        }

        [UIAction("LeagueReload")]
        public void LeagueReload()
        {
            if (LeaderboardInfoSemaphore.CurrentCount == 0 || AllResetSemaphore.CurrentCount == 0 || SetLeaderboardSemaphore.CurrentCount == 0)
                return;
            _ = this.LeagueReloadAsync();
        }

        [UIAction("JBSLLeagueFormatter")]
        public string JBSLLeagueFormatter(string leagueID)
        {
            if (string.Equals(leagueID, PlaceholderLeagueId, StringComparison.Ordinal))
                return this._isLeagueLoading ? LoadingLeagueText : NoLeagueDataText;
            if (!int.TryParse(leagueID, out var id))
                return "";

            var name = this._activeLeague.GetLeagueName(id);
            if (name == null)
                return "!ERROR!";
            return name;
        }

        public string LeaderboardFormat(string indexString, int subString = int.MaxValue, bool totalText = false)
        {
            if (string.Equals(indexString, PlaceholderLeaderboardId, StringComparison.Ordinal))
                return "";
            if (!int.TryParse(indexString, out var index))
                return "";
            if (!int.TryParse(this._jbslLeagueValue, out var leagueID) || leagueID == -1)
                return "";

            string result;
            if (index == 0)
            {
                if (totalText)
                    result = "#TOTAL RANKING#";
                else
                    result = this._activeLeague.GetLeagueName(leagueID);
            }
            else
                result = this._leaderboard.GetLeaderboardName(leagueID, index - 1);
            if (result == null)
                result = "!ERROR!";
            if (result.Length > subString)
                result = result.Substring(0, subString);
            return result;
        }

        [UIAction("LeaderboardFormatter")]
        public string LeaderboardFormatter(string indexString)
        {
            if (string.Equals(indexString, PlaceholderLeaderboardId, StringComparison.Ordinal))
                return this._isLeaderboardLoading ? LoadingLeaderboardText : NoLeaderboardDataText;
            return this.LeaderboardFormat(indexString, 20, true);
        }

        [UIAction("#post-parse")]
        public void PostParse()
        {
            this._init = true;
            var jbslLeagueLable = this._jbslLeagueTransform.GetComponentInChildren<CurvedTextMeshPro>();
            jbslLeagueLable.fontSize = 2.5f;
            jbslLeagueLable.enableWordWrapping = true;
            jbslLeagueLable.overflowMode = TextOverflowModes.Ellipsis;
            var leaderboardLabel = this._leaderboardTransform.GetComponentInChildren<CurvedTextMeshPro>();
            leaderboardLabel.fontSize = 2f;
            leaderboardLabel.enableWordWrapping = true;
            leaderboardLabel.overflowMode = TextOverflowModes.Ellipsis;
            if (this._virtualParticipationTransform != null && this._virtualParticipationTransform.GetComponent<CanvasGroup>() == null)
                this._virtualParticipationTransform.gameObject.AddComponent<CanvasGroup>();
            this.RefreshLeagueDropdown();
            this.RefreshLeaderboardDropdown();
            this.SyncVirtualParticipationValue();
            this.UpdateControlInteractivity();
            this._leaderboardMainViewController.SetTitle();
        }

        private void SetLeagueValueInternal(string value)
        {
            this._suppressLeagueSelectionChanged = true;
            try
            {
                this._jbslLeagueValue = string.IsNullOrEmpty(value) ? PlaceholderLeagueId : value;
            }
            finally
            {
                this._suppressLeagueSelectionChanged = false;
            }
            this.SyncVirtualParticipationValue();
        }

        private void SetLeaderboardValueInternal(string value)
        {
            this._suppressLeaderboardSelectionChanged = true;
            try
            {
                this._leaderboardValue = string.IsNullOrEmpty(value) ? PlaceholderLeaderboardId : value;
            }
            finally
            {
                this._suppressLeaderboardSelectionChanged = false;
            }

            if (!this._init)
                return;

            if (this._leaderboardValue == PlaceholderLeaderboardId)
                this._leaderboardMainViewController.SetTitle("");
            else
                this._leaderboardMainViewController.SetTitle(this.LeaderboardFormat(this._leaderboardValue));
        }

        private void SetChoices(List<object> choices, IEnumerable<object> values, string placeholderValue)
        {
            choices.Clear();
            if (values != null)
            {
                foreach (var value in values)
                    choices.Add(value);
            }
            if (choices.Count == 0)
                choices.Add(placeholderValue);
        }

        private void RefreshLeagueDropdown()
        {
            this.RefreshDropdown(this._jbslLeagueSetting, this.JBSLLeagueChoices);
        }

        private void RefreshLeaderboardDropdown()
        {
            this.RefreshDropdown(this._leaderboardSetting, this.LeaderboardChoices);
        }

        private void RefreshDropdown(DropDownListSetting dropdown, List<object> options)
        {
            if (dropdown == null)
                return;

            dropdown.Values = options;
            dropdown.UpdateChoices();
            dropdown.ReceiveValue();
        }

        private void UpdateControlInteractivity()
        {
            if (!this._init)
                return;

            var isBusy = LeaderboardInfoSemaphore.CurrentCount == 0 || AllResetSemaphore.CurrentCount == 0 || SetLeaderboardSemaphore.CurrentCount == 0 || this._isVirtualParticipationLoading;
            var hasLeagueData = !this.IsPlaceholderOnly(this.JBSLLeagueChoices, PlaceholderLeagueId);
            var hasLeaderboardData = !this.IsPlaceholderOnly(this.LeaderboardChoices, PlaceholderLeaderboardId);
            var hasVirtualParticipation = false;
            if (hasLeagueData && int.TryParse(this._jbslLeagueValue, out var leagueID) && leagueID != -1)
                hasVirtualParticipation = this._virtualLeagueService.IsVirtualParticipationAvailable(leagueID);

            this._jbslLeagueSetting.Interactable = !isBusy && hasLeagueData;
            this._leaderboardSetting.Interactable = !isBusy && hasLeaderboardData;
            this._leagueReloadButton.interactable = !isBusy;
            this._reloadButton.interactable = !isBusy && hasLeagueData;
            this._totalButton.interactable = !isBusy && this.LeaderboardChoices.Contains("0");
            if (this._virtualParticipationTransform != null)
            {
                foreach (var selectable in this._virtualParticipationTransform.GetComponentsInChildren<Selectable>(true))
                    selectable.interactable = !isBusy && hasVirtualParticipation;

                var canvasGroup = this._virtualParticipationTransform.GetComponent<CanvasGroup>();
                if (canvasGroup != null)
                    canvasGroup.alpha = hasVirtualParticipation ? 1f : 0.45f;
            }
        }

        private bool IsPlaceholderOnly(List<object> choices, string placeholderValue)
        {
            return choices.Count == 1 && string.Equals(choices[0] as string, placeholderValue, StringComparison.Ordinal);
        }

        private async Task SetVirtualParticipationEnabledAsync(bool enabled)
        {
            if (this._isVirtualParticipationLoading)
                return;

            if (!int.TryParse(this._jbslLeagueValue, out var leagueID) || leagueID == -1)
            {
                this.SyncVirtualParticipationValue();
                return;
            }

            if (enabled && !this._virtualLeagueService.IsVirtualParticipationAvailable(leagueID))
            {
                this.SyncVirtualParticipationValue();
                this.UpdateControlInteractivity();
                return;
            }

            this._isVirtualParticipationLoading = true;
            this.UpdateControlInteractivity();
            try
            {
                await this._virtualLeagueService.SetVirtualParticipationEnabledAsync(leagueID, enabled);
            }
            finally
            {
                this._isVirtualParticipationLoading = false;
                this.SyncVirtualParticipationValue();
                this.UpdateControlInteractivity();
                this._leaderboardMainViewController.SetRecords();
            }
        }

        private void SyncVirtualParticipationValue()
        {
            var value = false;
            if (int.TryParse(this._jbslLeagueValue, out var leagueID) && leagueID != -1)
            {
                this._virtualLeagueService.SyncLeagueParticipationState(leagueID);
                value = this._virtualLeagueService.IsVirtualParticipationEnabled(leagueID);
            }

            this._suppressVirtualParticipationChanged = true;
            try
            {
                this._virtualParticipationEnabled = value;
            }
            finally
            {
                this._suppressVirtualParticipationChanged = false;
            }

            if (this._init)
                this.NotifyPropertyChanged(nameof(this.VirtualParticipationEnabled));
            this._virtualParticipationSetting?.ReceiveValue();

            this.SyncVirtualProgressState();
        }

        private void EnsureVirtualLeagueEventSubscription()
        {
            if (this._virtualEventsSubscribed)
                return;

            this._virtualLeagueService.VirtualLeaderboardUpdated += this.HandleVirtualLeaderboardUpdated;
            this._virtualLeagueService.VirtualAvailabilityChanged += this.HandleVirtualAvailabilityChanged;
            this._virtualLeagueService.VirtualParticipationProgressChanged += this.HandleVirtualParticipationProgressChanged;
            this._virtualEventsSubscribed = true;
        }

        private void HandleVirtualLeaderboardUpdated(int leagueId)
        {
            if (!int.TryParse(this._jbslLeagueValue, out var currentLeagueId) || currentLeagueId != leagueId)
                return;

            this.SyncVirtualParticipationValue();
            this.UpdateControlInteractivity();
            this._leaderboardMainViewController.SetRecords();
        }

        private void HandleVirtualAvailabilityChanged(int leagueId)
        {
            if (!int.TryParse(this._jbslLeagueValue, out var currentLeagueId) || currentLeagueId != leagueId)
                return;

            this.SyncVirtualParticipationValue();
            this.UpdateControlInteractivity();
        }

        private void HandleVirtualParticipationProgressChanged(int leagueId, int completedMaps, int totalMaps, bool isActive)
        {
            this._virtualProgressLeagueId = leagueId;
            this._virtualProgressCompleted = completedMaps;
            this._virtualProgressTotal = totalMaps;
            this._virtualProgressActive = isActive;

            if (!int.TryParse(this._jbslLeagueValue, out var currentLeagueId) || currentLeagueId != leagueId)
                return;

            this.RfreshTimeUpdate();
        }

        private void SyncVirtualProgressState()
        {
            var leagueId = -1;
            if (int.TryParse(this._jbslLeagueValue, out var currentLeagueId) && currentLeagueId != -1)
                leagueId = currentLeagueId;

            if (leagueId != -1 && this._virtualLeagueService.TryGetVirtualParticipationProgress(leagueId, out var completedMaps, out var totalMaps, out var isActive))
            {
                this._virtualProgressLeagueId = leagueId;
                this._virtualProgressCompleted = completedMaps;
                this._virtualProgressTotal = totalMaps;
                this._virtualProgressActive = isActive;
            }
            else
            {
                this._virtualProgressLeagueId = leagueId;
                this._virtualProgressCompleted = 0;
                this._virtualProgressTotal = 0;
                this._virtualProgressActive = false;
            }

            this.RfreshTimeUpdate();
        }
    }
}

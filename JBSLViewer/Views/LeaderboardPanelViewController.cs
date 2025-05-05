using System;
using System.Threading;
using System.Threading.Tasks;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TMPro;
using HMUI;
using Zenject;
using SiraUtil.Zenject;
using BeatSaberMarkupLanguage.Attributes;
using BeatSaberMarkupLanguage.ViewControllers;
using BeatSaberMarkupLanguage.Components.Settings;
using JBSLViewer.Configuration;
using JBSLViewer.Models;

namespace JBSLViewer.Views
{
    [HotReload]
    public class LeaderboardPanelViewController : BSMLAutomaticViewController, IAsyncInitializable, ITickable
    {
        public bool _init = false;
        public float _currentCycleTime = 0f;
        public static SemaphoreSlim AllResetSemaphore = new SemaphoreSlim(1, 1);
        public static SemaphoreSlim SetLeaderboardSemaphore = new SemaphoreSlim(1, 1);
        public static SemaphoreSlim LeaderboardInfoSemaphore = new SemaphoreSlim(1, 1);

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

        public async Task InitializeAsync(CancellationToken token)
        {
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
            if (LeaderboardInfoSemaphore.CurrentCount == 0 || AllResetSemaphore.CurrentCount == 0 || SetLeaderboardSemaphore.CurrentCount == 0)
                return;
            if (!int.TryParse(this._jbslLeagueValue, out var leagueID))
                return;
            var time = (this._latestUpdate._latest + TimeSpan.FromMinutes(PluginConfig.Instance.refreshInterval) - DateTime.Now).ToString(@"mm\:ss");
            if (this._leaderboard._leaderboards.ContainsKey(leagueID) && this._latestUpdate._latest > this._leaderboard._leaderboards[leagueID].jbslViewerGetTime)
                _ = this.SetLeaderboardsAsync(this._leaderboardValue, true);
        }

        public async Task AllResetAsync()
        {
            if (this._init)
            {
                this._leagueReloadButton.interactable = false;
                this._reloadButton.interactable = false;
                this._totalButton.interactable = false;
            }
            await AllResetSemaphore.WaitAsync();
            try
            {
                this.JBSLLeagueChoices.Clear();
                if (this._init)
                    this._jbslLeagueSetting.UpdateChoices();
                this._leaderboardMainViewController.SetTitle("");
                await this._latestUpdate.GetHeadlineAsync();
                await this._activeLeague.GetActiveLeagueAsync();
                if (this._activeLeague._leagues == null || this._activeLeague._leagues.Count <= 0)
                    return;
                foreach (var league in this._activeLeague._leagues)
                    this.JBSLLeagueChoices.Add(league.id.ToString());
                if (this._init)
                    this._jbslLeagueSetting.UpdateChoices();
                if (this._activeLeague.GetLeagueIndex(PluginConfig.Instance.selectLeagueID) == -1)
                    PluginConfig.Instance.selectLeagueID = this._activeLeague._leagues[0].id;
                this.JBSLLeagueValue = PluginConfig.Instance.selectLeagueID.ToString();
                if (this._init)
                    this.NotifyPropertyChanged("JBSLLeagueValue");
            }
            finally
            {
                AllResetSemaphore.Release();
            }
            await this.SetLeaderboardsAsync();
            if (this._init)
            {
                this._leagueReloadButton.interactable = true;
                this._reloadButton.interactable = true;
                this._totalButton.interactable = true;
            }
        }

        public async Task SetLeaderboardsAsync(string indexString = "0", bool reload = false)
        {
            int leagueID;
            if (this._init)
            {
                this._leagueReloadButton.interactable = false;
                this._reloadButton.interactable = false;
                this._totalButton.interactable = false;
            }
            await SetLeaderboardSemaphore.WaitAsync();
            try
            {
                if (!int.TryParse(this._jbslLeagueValue, out leagueID))
                    return;
                if (this._activeLeague.GetLeagueIndex(leagueID) == -1)
                    return;
                PluginConfig.Instance.selectLeagueID = leagueID;
                this.LeaderboardChoices.Clear();
                if (this._init)
                    this._leaderboardSetting.UpdateChoices();
                this._leaderboardMainViewController.SetTitle("");
                await this._leaderboard.GetLeaderboardAsync(leagueID, reload);
                if (!this._leaderboard._leaderboards.ContainsKey(leagueID))
                    return;
                var leaderboard = this._leaderboard._leaderboards[leagueID];
                if (leaderboard == null)
                    return;
                if (leaderboard.maps == null)
                    return;
                for (int i = 0; i <= leaderboard.maps.Count; i++)
                    this.LeaderboardChoices.Add(i.ToString());
            }
            finally
            {
                SetLeaderboardSemaphore.Release();
            }
            this.LeaderboardValue = indexString;
            if (this._init)
            {
                this._leaderboardSetting.UpdateChoices();
                this.NotifyPropertyChanged("LeaderboardValue");
            }
            if (this._init)
                this._totalButton.interactable = true;
            await LeaderboardInfoSemaphore.WaitAsync();
            try
            {
                await this._leaderboardInfo.SetLeagueMapDataAsync(leagueID);
            }
            finally
            {
                LeaderboardInfoSemaphore.Release();
            }
            if (this._init)
            {
                this._leagueReloadButton.interactable = true;
                this._reloadButton.interactable = true;
            }
        }

        public async Task LeagueReloadAsync()
        {
            this.JBSLLeagueChoices.Clear();
            this.LeaderboardChoices.Clear();
            if (this._init)
            {
                this._leaderboardSetting.UpdateChoices();
                this._jbslLeagueSetting.UpdateChoices();
            }
            await this.AllResetAsync();
        }

        public void RfreshTimeUpdate()
        {
            var time = (this._latestUpdate._latest + TimeSpan.FromMinutes(PluginConfig.Instance.refreshInterval) - DateTime.Now).ToString(@"mm\:ss");
            if (this._init)
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

        [UIValue("JBSLLeagueChoices")]
        public List<object> JBSLLeagueChoices { get; set; } = new List<object>();

        [UIValue("LeaderboardChoices")]
        public List<object> LeaderboardChoices { get; set; } = new List<object>();

        private string _jbslLeagueValue;
        [UIValue("JBSLLeagueValue")]
        public string JBSLLeagueValue
        {
            get => this._jbslLeagueValue;
            set
            {
                this._jbslLeagueValue = value;
                if (LeaderboardInfoSemaphore.CurrentCount == 0 || AllResetSemaphore.CurrentCount == 0 || SetLeaderboardSemaphore.CurrentCount == 0)
                    return;
                _ = this.SetLeaderboardsAsync();
            }
        }

        private string _leaderboardValue;
        [UIValue("LeaderboardValue")]
        public string LeaderboardValue
        {
            get => this._leaderboardValue;
            set
            {
                this._leaderboardValue = value;
                this._leaderboardMainViewController.SetTitle(this.LeaderboardFormat(value));
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
            if (!int.TryParse(leagueID, out var id))
                return "";
            var name = this._activeLeague.GetLeagueName(id);
            if (name == null)
                return "!ERROR!";
            return name;
        }

        public string LeaderboardFormat(string indexString, int subString = int.MaxValue, bool totalText = false)
        {
            if (!int.TryParse(indexString, out var index))
                return "";
            if (!int.TryParse(this._jbslLeagueValue, out var leagueID))
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
            this.NotifyPropertyChanged("JBSLLeagueValue");
            this.NotifyPropertyChanged("LeaderboardValue");
            this._leaderboardMainViewController.SetTitle();
        }
    }
}

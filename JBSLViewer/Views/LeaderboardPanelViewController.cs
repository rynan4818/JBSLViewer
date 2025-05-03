using System;
using System.Threading;
using System.Threading.Tasks;
using System.Collections.Generic;
using UnityEngine;
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
        public bool _tickStop = false;
        public float _currentCycleTime = 0f;
        [Inject]
        private readonly ActiveLeague _activeLeague;
        [Inject]
        private readonly Leaderboard _leaderboard;
        [Inject]
        private readonly LatestUpdate _latestUpdate;
        [Inject]
        private readonly LeaderboardMainViewController _leaderboardMainViewController;

        public async Task InitializeAsync(CancellationToken token)
        {
            await this.AllResetAsync();
        }

        public void Tick()
        {
            if (!this.isActivated || !this._init || this._tickStop)
                return;
            if (this._currentCycleTime >= 1f)
            {
                this._currentCycleTime = 0f;
                this._latestUpdate.RefrashLatest();
                var leagueID = int.Parse(this._jbslLeagueValue);
                if (this._leaderboard._leaderboards.ContainsKey(leagueID) && this._latestUpdate._latest >= this._leaderboard._leaderboards[leagueID].jbslViewerGetTime)
                    _ = this.SetLeaderboardsAsync(this._leaderboardValue, true);
                this.RfreshTimeUpdate();
            }
            this._currentCycleTime += Time.deltaTime;
        }

        public async Task SetLeaguesAsync()
        {
            this.JBSLLeagueChoices.Clear();
            if (this._init)
                this._jbslLeagueSetting.UpdateChoices();
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

        public async Task SetLeaderboardsAsync(string indexString = "0", bool reload = false)
        {
            var leagueID = int.Parse(this._jbslLeagueValue);
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
            this.LeaderboardValue = indexString;
            if (this._init)
            {
                this._leaderboardSetting.UpdateChoices();
                this.NotifyPropertyChanged("LeaderboardValue");
            }
        }

        public async Task AllResetAsync()
        {
            await this._latestUpdate.GetHeadlineAsync();
            await this.SetLeaguesAsync();
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
            this._tickStop = true;
            await this.AllResetAsync();
            this._tickStop = false;
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
            this.LeaderboardValue = "0";
            if (this._init)
                this.NotifyPropertyChanged("LeaderboardValue");
        }

        [UIAction("Reload")]
        public void Reload()
        {
            _ = this.SetLeaderboardsAsync(this._leaderboardValue, true);
        }

        [UIAction("LeagueReload")]
        public void LeagueReload()
        {
            _ = this.LeagueReloadAsync();
        }

        [UIAction("JBSLLeagueFormatter")]
        public string JBSLLeagueFormatter(string leagueID)
        {
            if (leagueID == null)
                return "";
            var name = this._activeLeague.GetLeagueName(int.Parse(leagueID));
            if (name == null)
                return "!ERROR!";
            return name;
        }

        public string LeaderboardFormat(string indexString, int subString = int.MaxValue, bool totalText = false)
        {
            if (indexString == null)
                return "";
            var index = int.Parse(indexString);
            string result;
            if (index == 0)
            {
                if (totalText)
                    result = "#TOTAL RANKING#";
                else
                    result = this._activeLeague.GetLeagueName(int.Parse(this._jbslLeagueValue));
            }
            else
                result = this._leaderboard.GetLeaderboardName(int.Parse(this._jbslLeagueValue), index - 1);
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

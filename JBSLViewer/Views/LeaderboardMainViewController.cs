using System.Linq;
using System.Collections.Generic;
using UnityEngine;
using HMUI;
using TMPro;
using Zenject;
using BeatSaberMarkupLanguage;
using BeatSaberMarkupLanguage.Attributes;
using BeatSaberMarkupLanguage.Components;
using BeatSaberMarkupLanguage.ViewControllers;
using JBSLViewer.Models;
using JBSLViewer.Models.JBSL;

namespace JBSLViewer.Views
{
    [HotReload]
    public class LeaderboardMainViewController : BSMLAutomaticViewController
    {
        public bool _init = false;
        public int _page = 0;
        [Inject]
        private readonly Leaderboard _leaderboard;
        [Inject]
        private readonly LeaderboardPanelViewController _leaderboardPanelViewController;

        [UIComponent("list")]
        public readonly CustomCellListTableData _list;

        [UIValue("entries")]
        public readonly List<object> _records = new List<object>();

        [UIComponent("Title")]
        private readonly TextMeshProUGUI _title;

        [UIComponent("TitileBar")]
        private readonly Backgroundable _titileBar;

        [UIAction("PageUp")]
        public void PageUp()
        {
            this._page--;
            this.SetRecords();
        }

        [UIAction("PageDown")]
        public void PageDown()
        {
            this._page++;
            this.SetRecords();
        }

        [UIAction("#post-parse")]
        public void PostParse()
        {
            this._init = true;
            var color = new Color32(228, 144, 50, 255);
            this._titileBar.background.material = Utilities.ImageResources.NoGlowMat;
            var imageView = this._titileBar.background as ImageView;
            imageView.color = color;
            imageView.color0 = color;
            imageView.color1 = color;
            imageView._skew = 0.18f;
            imageView._gradient = true;
            this.SetTitle();
        }

        public void SetTitle(string title = null)
        {
            if (!this._init)
                return;
            if (title == null)
                this._title.text = this._leaderboardPanelViewController.GetLeaderboardName();
            else
                this._title.text = title;
            this._page = 0;
            if (this._leaderboardPanelViewController.LeaderboardValue == "0")
                this._title.fontSize = 6f;
            else
                this._title.fontSize = 3f;
            this.SetRecords();
        }
        public void SetRecords()
        {
            this._records.Clear();
            this._list.tableView.ReloadData();
            if (LeaderboardPanelViewController.AllResetSemaphore.CurrentCount == 0 || LeaderboardPanelViewController.SetLeaderboardSemaphore.CurrentCount == 0)
                return;
            if (!int.TryParse(this._leaderboardPanelViewController.JBSLLeagueValue, out var leagueID))
                return;
            if (!int.TryParse(this._leaderboardPanelViewController.LeaderboardValue, out var index))
                return;
            List<Score> scores;
            if (index == 0)
                scores = this._leaderboard.GetTotalLeaderboard(leagueID);
            else
                scores = this._leaderboard.GetMapLeaderboard(leagueID, index - 1);
            if (scores == null)
                return;
            var maxPage = (scores.Count - 1) / 10;
            if (maxPage < this._page)
                this._page = maxPage;
            if (this._page < 0)
                this._page = 0;
            foreach (var score in scores.Skip(this._page * 10).Take(10))
            {
                var record = new Record($"#{score.standing}", score.name, score.pos.ToString(), $"{score.acc:F2}%");
                this._records.Add(record);
            }
            this._list.tableView.ReloadData();
        }

        public class Record
        {
            [UIValue("standing")]
            public string _standing { get; }

            [UIValue("name")]
            public string _name { get; }

            [UIValue("pos")]
            public string _pos { get; }

            [UIValue("acc")]
            public string _acc { get; }

            public Record(string standing, string name, string pos, string acc)
            {
                _standing = standing;
                _name = name;
                _pos = pos;
                _acc = acc;
            }
        }
    }
}

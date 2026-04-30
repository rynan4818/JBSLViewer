using System;
using System.Linq;
using System.Collections.Generic;
using BS_Utils.Gameplay;
using HMUI;
using TMPro;
using UnityEngine;
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
        private static readonly Color32 SelfColor = new Color32(90, 210, 255, 255);
        private static readonly Color32 ValidColor = new Color32(110, 255, 145, 255);
        private static readonly Color32 InvalidColor = new Color32(150, 150, 150, 255);

        public bool _init = false;
        public int _page = 0;
        private bool _selfSidRequested = false;
        private string _selfSid;

        [Inject]
        private readonly ActiveLeague _activeLeague;
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
            imageView.gradient = true;
            imageView.SetVerticesDirty();
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

        public bool TryRefreshCurrentUserSid()
        {
            if (!string.IsNullOrEmpty(this._selfSid))
                return false;

            if (!this._selfSidRequested)
            {
                GetUserInfo.UpdateUserInfo();
                this._selfSidRequested = true;
            }

            var sid = GetUserInfo.GetUserID();
            if (string.IsNullOrEmpty(sid) || string.Equals(this._selfSid, sid, StringComparison.Ordinal))
                return false;

            this._selfSid = sid;
            return true;
        }

        public void SetRecords()
        {
            if (!this._init || this._list == null)
                return;

            this.TryRefreshCurrentUserSid();
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

            var validityContext = this._leaderboard.BuildValidityContext(leagueID, Math.Max(this._activeLeague.GetLeagueMaxValid(leagueID), 0));
            var maxPage = Math.Max(0, (scores.Count - 1) / 10);
            if (maxPage < this._page)
                this._page = maxPage;
            if (this._page < 0)
                this._page = 0;

            if (index == 0)
            {
                foreach (var score in scores.Skip(this._page * 10).Take(10))
                {
                    validityContext.TryGetSummary(score.sid, out var summary);
                    var record = new Record(
                        $"#{score.standing}",
                        score.name ?? string.Empty,
                        score.pos.ToString(),
                        summary?.ValidCount.ToString() ?? "0",
                        $"{score.acc:F2}%",
                        this.IsCurrentUser(score.sid),
                        false,
                        true,
                        summary?.PosTooltip,
                        summary?.ValidTooltip,
                        summary?.AccTooltip);
                    this._records.Add(record);
                }
            }
            else
            {
                var mapIndex = index - 1;
                foreach (var score in scores.Skip(this._page * 10).Take(10))
                {
                    var isValid = validityContext.IsValidScore(mapIndex, score.sid);
                    var record = new Record(
                        $"#{score.standing}",
                        score.name ?? string.Empty,
                        score.pos.ToString(),
                        isValid ? "O" : "-",
                        $"{score.acc:F2}%",
                        this.IsCurrentUser(score.sid),
                        isValid,
                        false,
                        null,
                        null,
                        null);
                    this._records.Add(record);
                }
            }

            this._list.tableView.ReloadData();
        }

        private bool IsCurrentUser(string sid)
        {
            return !string.IsNullOrEmpty(this._selfSid) && string.Equals(this._selfSid, sid, StringComparison.Ordinal);
        }

        public class Record
        {
            [UIValue("standing")]
            public string _standing { get; }

            [UIValue("name")]
            public string _name { get; }

            [UIValue("pos")]
            public string _pos { get; }

            [UIValue("valid")]
            public string _valid { get; }

            [UIValue("acc")]
            public string _acc { get; }

            private readonly bool _isCurrentUser;
            private readonly bool _isMapValid;
            private readonly bool _isTotalRecord;
            private readonly string _posTooltip;
            private readonly string _validTooltip;
            private readonly string _accTooltip;

            [UIComponent("StandingText")]
            private readonly TextMeshProUGUI _standingText;

            [UIComponent("NameText")]
            private readonly TextMeshProUGUI _nameText;

            [UIComponent("PosText")]
            private readonly TextMeshProUGUI _posText;

            [UIComponent("ValidText")]
            private readonly TextMeshProUGUI _validText;

            [UIComponent("AccText")]
            private readonly TextMeshProUGUI _accText;

            public Record(string standing, string name, string pos, string valid, string acc, bool isCurrentUser, bool isMapValid, bool isTotalRecord, string posTooltip, string validTooltip, string accTooltip)
            {
                this._standing = standing;
                this._name = name;
                this._pos = pos;
                this._valid = valid;
                this._acc = acc;
                this._isCurrentUser = isCurrentUser;
                this._isMapValid = isMapValid;
                this._isTotalRecord = isTotalRecord;
                this._posTooltip = posTooltip;
                this._validTooltip = validTooltip;
                this._accTooltip = accTooltip;
            }

            [UIAction("#post-parse")]
            public void PostParse()
            {
                Color mainColor = this._isCurrentUser ? (Color)SelfColor : Color.white;
                ApplyColor(this._standingText, mainColor);
                ApplyColor(this._nameText, mainColor);
                ApplyColor(this._posText, mainColor);
                ApplyColor(this._accText, mainColor);

                if (this._isTotalRecord)
                    ApplyColor(this._validText, mainColor);
                else
                    ApplyColor(this._validText, this._isMapValid ? ValidColor : InvalidColor);

                AddHoverHint(this._posText, this._posTooltip);
                AddHoverHint(this._validText, this._validTooltip);
                AddHoverHint(this._accText, this._accTooltip);
            }

            private static void ApplyColor(TMP_Text text, Color color)
            {
                if (text != null)
                    text.color = color;
            }

            private static void AddHoverHint(TMP_Text text, string tooltip)
            {
                if (text == null || string.IsNullOrWhiteSpace(tooltip))
                    return;

                text.raycastTarget = true;
                var hoverHint = text.GetComponent<HoverHint>();
                if (hoverHint == null)
                    hoverHint = BeatSaberMarkupLanguage.BeatSaberUI.DiContainer.InstantiateComponent<HoverHint>(text.gameObject);
                else
                    BeatSaberMarkupLanguage.BeatSaberUI.DiContainer.Inject(hoverHint);
                hoverHint.text = tooltip;
            }
        }
    }
}

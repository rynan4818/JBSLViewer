/*
Portions copied/adapted from TournamentAssistant.
Source: https://github.com/MatrikMoon/TournamentAssistant?tab=MIT-1-ov-file
Original: TournamentAssistant/UI/ViewControllers/ItemSelection.cs; TournamentAssistant/UI/CustomListItems/GenericItem.cs
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
#pragma warning disable CS0649
using System;
using System.Collections.Generic;
using System.Linq;
using BeatSaberMarkupLanguage.Attributes;
using BeatSaberMarkupLanguage.Components;
using BeatSaberMarkupLanguage.ViewControllers;
using HMUI;
using JBSLViewer.Models.JBSL;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace JBSLViewer.Qualifier.UI
{
    public sealed class QualifierLeagueSelectionViewController : BSMLAutomaticViewController
    {
        public event Action<int> ItemSelected;
        public event Action ReloadRequested;
        [UIComponent("item-list")] private CustomCellListTableData itemList;
        [UIComponent("status")] private TextMeshProUGUI status;
        [UIComponent("league-controls")] private RectTransform controls;
        [UIComponent("league-notice")] private ModalView notice;
        [UIComponent("notice-title")] private TextMeshProUGUI noticeTitle;
        [UIComponent("notice-league")] private TextMeshProUGUI noticeLeague;
        [UIComponent("notice-message")] private TextMeshProUGUI noticeMessage;
        [UIValue("items")] private readonly List<object> items = new List<object>();
        private string _status = "Loading leagues...";
        private bool _busy;
        private CanvasGroup _controlsGroup;
        public bool NoticeShown { get; private set; }
        public int SelectedIndex { get; private set; }
        protected override void DidActivate(bool firstActivation, bool addedToHierarchy, bool screenSystemEnabling)
        {
            base.DidActivate(firstActivation, addedToHierarchy, screenSystemEnabling);
            itemList.TableView.ClearSelection();
        }
        public void SetItems(IEnumerable<LeagueJson> leagues)
        {
            items.Clear();
            if (leagues != null) items.AddRange(leagues.Select(x => new LeagueItem(x)));
            itemList?.TableView.ReloadData();
        }
        public void SetStatus(string text) { _status = text; if (status != null) status.text = text; }
        [UIAction("#post-parse")] private void Parsed()
        {
            status.richText = noticeTitle.richText = noticeLeague.richText = noticeMessage.richText = false;
            _controlsGroup = controls.GetComponent<CanvasGroup>() ?? controls.gameObject.AddComponent<CanvasGroup>();
            SetStatus(_status);
            SetBusy(_busy);
        }
        public void SetBusy(bool busy)
        {
            _busy = busy;
            if (_controlsGroup != null) _controlsGroup.interactable = _controlsGroup.blocksRaycasts = !busy && !NoticeShown;
        }
        public void ShowNotice(string title, string league, string message)
        {
            noticeTitle.text = title;
            noticeLeague.text = league;
            noticeMessage.text = message;
            if (!NoticeShown) notice.Show(false, false);
            NoticeShown = true;
            SetBusy(_busy);
        }
        public bool HideNotice()
        {
            if (!NoticeShown) return false;
            NoticeShown = false;
            if (notice != null) notice.Hide(false);
            itemList?.TableView.ClearSelection();
            SetBusy(_busy);
            return true;
        }
        [UIAction("notice-ok")] private void CloseNotice() => HideNotice();
        [UIAction("item-selected")] private void ItemClicked(TableView sender, LeagueItem item)
        {
            if (_busy || NoticeShown) { sender.ClearSelection(); return; }
            SelectedIndex = items.IndexOf(item); ItemSelected?.Invoke(item.Id);
        }
        public void RestorePosition(int index)
        {
            if (itemList != null && items.Count > 0)
                itemList.TableView.ScrollToCellWithIdx(Math.Max(0, Math.Min(index, items.Count - 1)), TableView.ScrollPositionType.Beginning, false);
        }
        [UIAction("reload")] private void Reload() { if (!_busy && !NoticeShown) ReloadRequested?.Invoke(); }
        protected override void DidDeactivate(bool removedFromHierarchy, bool screenSystemDisabling)
        {
            if (removedFromHierarchy || screenSystemDisabling) HideNotice();
            base.DidDeactivate(removedFromHierarchy, screenSystemDisabling);
        }
        protected override void OnDestroy() { HideNotice(); base.OnDestroy(); }

        private sealed class LeagueItem
        {
            public int Id { get; }
            [UIValue("item-name")] private readonly string name;
            [UIValue("item-details")] private readonly string details;
            [UIComponent("item-details-text")] private TextMeshProUGUI detailsText;
            [UIComponent("bg")] private RawImage background;
            public LeagueItem(LeagueJson item)
            {
                Id = item.id;
                // Escape user-controlled markup because the original row binds directly to text.
                name = item.name?.Replace("<", "\uFF1C").Replace(">", "\uFF1E") ?? "League " + Id;
                details = "League " + Id;
            }
            [UIAction("refresh-visuals")] private void Refresh(bool selected, bool highlighted)
            {
                background.texture = Texture2D.whiteTexture;
                background.color = new Color(1, 1, 1, .125f);
                detailsText.color = new Color(.65f, .65f, .65f, 1);
            }
        }
    }
}

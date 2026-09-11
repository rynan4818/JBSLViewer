/*
Portions copied/adapted from TournamentAssistant.
Source: https://github.com/MatrikMoon/TournamentAssistant?tab=MIT-1-ov-file
Original: TournamentAssistant/UI/ViewControllers/SongSelection.cs
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
using BeatSaberMarkupLanguage.Attributes;
using BeatSaberMarkupLanguage.Components;
using BeatSaberMarkupLanguage.ViewControllers;
using HMUI;
using TMPro;

namespace JBSLViewer.Qualifier.UI
{
    public sealed class QualifierSongSelectionViewController : BSMLAutomaticViewController
    {
        public event Action<QualifierSongListItem> SongSelected;
        public event Action ReloadRequested;
        [UIComponent("song-list")] private CustomCellListTableData songList;
        [UIComponent("status")] private TextMeshProUGUI status;
        [UIValue("maps")] private readonly List<object> maps = new List<object>();
        private string _status = "Loading maps...";
        protected override void DidActivate(bool firstActivation, bool addedToHierarchy, bool screenSystemEnabling)
        {
            base.DidActivate(firstActivation, addedToHierarchy, screenSystemEnabling);
            songList.TableView.ClearSelection();
        }
        public void SetSongs(IEnumerable<QualifierSongListItem> songs)
        {
            DisposeItems();
            if (songs != null) foreach (var song in songs) maps.Add(song);
            songList?.TableView.ReloadData();
        }
        public void SetStatus(string text) { _status = text; if (status != null) status.text = text; }
        public int IndexOf(QualifierSongListItem item) => maps.IndexOf(item);
        public void RestorePosition(int index)
        {
            if (songList != null && maps.Count > 0)
                songList.TableView.ScrollToCellWithIdx(Math.Max(0, Math.Min(index, maps.Count - 1)), TableView.ScrollPositionType.Beginning, false);
        }
        [UIAction("#post-parse")] private void Parsed() { status.richText = false; SetStatus(_status); }
        [UIAction("song-selected")] private void SongClicked(TableView sender, QualifierSongListItem item) => SongSelected?.Invoke(item);
        [UIAction("reload")] private void Reload() => ReloadRequested?.Invoke();
        public void DisposeItems()
        {
            foreach (QualifierSongListItem item in maps) item.Dispose();
            maps.Clear();
        }
        protected override void OnDestroy() { DisposeItems(); base.OnDestroy(); }
    }
}

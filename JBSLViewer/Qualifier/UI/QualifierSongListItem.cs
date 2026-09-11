/*
Portions copied/adapted from TournamentAssistant.
Source: https://github.com/MatrikMoon/TournamentAssistant?tab=MIT-1-ov-file
Original: TournamentAssistant/UI/CustomListItems/SongListItem.cs
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
using System.Threading;
using BeatSaberMarkupLanguage.Attributes;
using JBSLViewer.Qualifier.Core.Contracts;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace JBSLViewer.Qualifier.UI
{
    // Original SongListItem created by Moon on 9/8/2020.
    public sealed class QualifierSongListItem : IDisposable
    {
        public QualifierMap Map { get; }
        public BeatmapLevel Level { get; }
        [UIComponent("song-name-text")] private TextMeshProUGUI songNameText;
        [UIComponent("song-details-text")] private TextMeshProUGUI songDetailsText;
        [UIComponent("cover-image")] private RawImage coverImage;
        [UIComponent("loading-bg")] private RawImage loadingBackground;
        [UIComponent("hover-bg")] private RawImage hoverBackground;
        private readonly CancellationTokenSource _lifetime = new CancellationTokenSource();
        private bool _disposed;
        private int _renderGeneration;
        private string _error;

        public QualifierSongListItem(QualifierMap map, BeatmapLevel level) { Map = map; Level = level; }
        public void SetError(string error) { _error = error; UpdateText(); }
        private void UpdateText()
        {
            if (songNameText == null) return;
            songNameText.richText = songDetailsText.richText = false;
            songNameText.text = Level?.songName ?? Map.Title ?? Map.Hash;
            songDetailsText.text = _error ?? (Level == null ? "NOT INSTALLED - install this map, then RELOAD"
                : Map.Characteristic + " / " + Map.Difficulty.Replace("Plus", "+") + "  [" + string.Join(", ", Level.allMappers ?? new string[0]) + "]");
            loadingBackground.color = Level == null || _error != null ? new Color(1, 0, 0, .2f) : Color.clear;
        }
        [UIAction("refresh-visuals")] private async void Refresh(bool selected, bool highlighted)
        {
            var generation = ++_renderGeneration;
            hoverBackground.texture = loadingBackground.texture = Texture2D.whiteTexture;
            hoverBackground.color = new Color(1, 1, 1, .125f);
            songDetailsText.color = new Color(.65f, .65f, .65f, 1);
            coverImage.texture = null;
            UpdateText();
            if (Level == null || _disposed) return;
            try
            {
                var cover = await Level.previewMediaData.GetCoverSpriteAsync();
                if (_disposed || generation != _renderGeneration || coverImage == null) return;
                // Crop the shared texture through UV coordinates; never destroy a game-owned cover.
                coverImage.uvRect = new Rect(0, .4f, 1, 1f / 6);
                coverImage.texture = cover?.texture;
            }
            catch (OperationCanceledException) { }
            catch (Exception ex) { Plugin.Log.Debug("Challenge cover unavailable: " + ex.GetType().Name); }
        }
        public void Dispose() { if (_disposed) return; _disposed = true; _lifetime.Cancel(); _lifetime.Dispose(); }
    }
}

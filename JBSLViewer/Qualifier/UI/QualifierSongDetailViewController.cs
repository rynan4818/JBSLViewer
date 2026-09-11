/*
Portions copied/adapted from TournamentAssistant.
Source: https://github.com/MatrikMoon/TournamentAssistant?tab=MIT-1-ov-file
Original: TournamentAssistant/UI/ViewControllers/SongDetail.cs; TournamentAssistant/Utilities/SongUtils.cs (GetJumpDistance)
Revision: ab4021a49f889bc36059efe3d8a2431097f1ffa5
Note-jump API adaptation: d52c64d00ad7c84e073fe5c306928b5892cd47db (TournamentAssistant/UI/ViewControllers/SongDetail.cs)

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
using System.Linq;
using System.Threading;
using BeatSaberMarkupLanguage.Attributes;
using BeatSaberMarkupLanguage.ViewControllers;
using HMUI;
using JBSLViewer.Qualifier.Core;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace JBSLViewer.Qualifier.UI
{
    public sealed class QualifierSongDetailViewController : BSMLAutomaticViewController
    {
        public event Action ChallengePressed, PracticePressed, ConfirmPressed, CancelPressed;
        [UIComponent("level-details-rect")] private RectTransform levelDetailsRect;
        [UIComponent("song-name-text")] private TextMeshProUGUI songNameText;
        [UIComponent("duration-text")] private TextMeshProUGUI durationText;
        [UIComponent("bpm-text")] private TextMeshProUGUI bpmText;
        [UIComponent("nps-text")] private TextMeshProUGUI npsText;
        [UIComponent("njs-text")] private TextMeshProUGUI njsText;
        [UIComponent("jump-distance-text")] private TextMeshProUGUI jumpDistanceText;
        [UIComponent("notes-count-text")] private TextMeshProUGUI notesCountText;
        [UIComponent("obstacles-count-text")] private TextMeshProUGUI obstaclesCountText;
        [UIComponent("bombs-count-text")] private TextMeshProUGUI bombsCountText;
        [UIComponent("level-cover-image")] private RawImage levelCoverImage;
        [UIComponent("characteristic-control")] private IconSegmentedControl characteristicControl;
        [UIComponent("difficulty-control")] private TextSegmentedControl difficultyControl;
        [UIComponent("characteristic-control-blocker")] private RawImage characteristicBlocker;
        [UIComponent("difficulty-control-blocker")] private RawImage difficultyBlocker;
        [UIComponent("play-button")] private Button challengeButton;
        [UIComponent("practice-button")] private Button practiceButton;
        [UIComponent("confirmation")] private ModalView confirmation;
        [UIComponent("confirm-text")] private TextMeshProUGUI confirmText;
        [UIComponent("confirm")] private Button confirmButton;
        [UIComponent("cancel")] private Button cancelButton;
        private QualifierBeatmap _map;
        private CancellationTokenSource _content;
        private int _generation;
        private bool _modalShown;
        private Material _maskMaterial;

        [UIAction("#post-parse")] private void Parsed()
        {
            songNameText.richText = confirmText.richText = false;
            levelCoverImage.color = new Color(.5f, .5f, .5f, .5f);
            characteristicBlocker.color = difficultyBlocker.color = Color.clear;
            var mask = levelDetailsRect.gameObject.AddComponent<Mask>();
            mask.showMaskGraphic = true;
            var maskImage = levelDetailsRect.gameObject.AddComponent<Image>();
            var material = Resources.FindObjectsOfTypeAll<Material>().FirstOrDefault(m => m.name == "UINoGlow");
            if (material != null) { _maskMaterial = new Material(material); maskImage.material = _maskMaterial; }
            maskImage.sprite = Resources.FindObjectsOfTypeAll<Sprite>().FirstOrDefault(x => x.name == "RoundRectPanel");
            maskImage.type = Image.Type.Sliced;
            maskImage.color = new Color(0, 0, 0, .25f);
            SetSong(_map);
        }
        public async void SetSong(QualifierBeatmap map)
        {
            _map = map;
            var generation = ++_generation;
            _content?.Cancel(); _content?.Dispose();
            _content = new CancellationTokenSource();
            var token = _content.Token;
            if (songNameText == null || map == null) return;
            var level = map.Level;
            var characteristic = map.Key.beatmapCharacteristic;
            songNameText.text = level.songName;
            var duration = level.songDuration;
            durationText.text = TimeSpan.FromSeconds(Math.Max(0, duration)).ToString(@"m\:ss");
            bpmText.text = Mathf.RoundToInt(level.beatsPerMinute).ToString();
            npsText.text = njsText.text = jumpDistanceText.text = notesCountText.text = obstaclesCountText.text = bombsCountText.text = "--";
            levelCoverImage.texture = null;
            characteristicControl.SetData(new[] { new IconSegmentedControl.DataItem(characteristic.icon, characteristic.serializedName) });
            characteristicControl.SelectCellWithNumber(0);
            difficultyControl.SetTexts(new[] { map.Key.difficulty.ToString().Replace("Plus", "+") });
            difficultyControl.SelectCellWithNumber(0);
            try
            {
                var cover = await level.previewMediaData.GetCoverSpriteAsync();
                if (generation != _generation || token.IsCancellationRequested || levelCoverImage == null) return;
                levelCoverImage.texture = cover?.texture;
            }
            catch (OperationCanceledException) { return; }
            catch (Exception ex) { Plugin.Log.Debug("Challenge song cover unavailable: " + ex.GetType().Name); }
            if (generation != _generation || token.IsCancellationRequested) return;
            try
            {
                var metadata = level.GetDifficultyBeatmapData(characteristic, map.Key.difficulty);
                var data = map.BasicInfo;
                if (generation != _generation || token.IsCancellationRequested || npsText == null) return;
                var njs = BeatmapDifficultyMethods.NoteJumpMovementSpeed(map.Key.difficulty, metadata.noteJumpMovementSpeed, false);
                npsText.text = duration > 0 ? (data.cuttableNotesCount / duration).ToString("0.00") : "--";
                njsText.text = njs.ToString("0.0#");
                jumpDistanceText.text = GetJumpDistance(level.beatsPerMinute, njs, metadata.noteJumpStartBeatOffset).ToString("0.0#");
                notesCountText.text = data.cuttableNotesCount.ToString();
                obstaclesCountText.text = data.obstaclesCount.ToString();
                bombsCountText.text = data.bombsCount.ToString();
            }
            catch (OperationCanceledException) { }
            catch (Exception ex) { Plugin.Log.Warn("Challenge song details unavailable: " + ex.GetType().Name); }
        }
        private static float GetJumpDistance(float bpm, float njs, float offset)
        {
            if (bpm <= 0 || njs <= 0) return 0;
            var secondsPerBeat = 60f / bpm;
            var halfJump = 4f;
            while (njs * secondsPerBeat * halfJump > 17.999f) halfJump /= 2;
            halfJump = Math.Max(halfJump + offset, .25f);
            return njs * secondsPerBeat * halfJump * 2;
        }
        public void SetState(QualifierViewState state, bool configured, bool canPractice, bool locked)
        {
            if (challengeButton == null) return;
            challengeButton.interactable = _map != null && state.CanChallenge && configured;
            practiceButton.interactable = _map != null && canPractice && !locked;
            confirmButton.interactable = state.CanConfirm && configured;
            cancelButton.interactable = state.ConfirmationOpen && locked;
            if (_modalShown && !state.ConfirmationOpen) { confirmation.Hide(false); _modalShown = false; }
        }
        public void ShowConfirmation(SelectionSnapshot selection, int? remaining)
        {
            confirmText.text = "Start a Qualifier challenge?\n\n" + selection.Leaderboard?.Title + "\n"
                + selection.SongTitle + "\n" + selection.Map?.Characteristic + " / " + selection.Map?.Difficulty
                + "\n\nRemaining: " + remaining
                + "\nOne attempt is consumed when the reservation succeeds.\nQuit, Restart or a failed start does not refund it.";
            _modalShown = true;
            confirmation.Show(true, true);
        }
        public void HideConfirmation()
        {
            if (_modalShown && confirmation != null) confirmation.Hide(false);
            _modalShown = false;
        }
        [UIAction("characteristic-selected")] private void CharacteristicSelected(IconSegmentedControl control, int index) { }
        [UIAction("difficulty-selected")] private void DifficultySelected(TextSegmentedControl control, int index) { }
        [UIAction("play-pressed")] private void Challenge() => ChallengePressed?.Invoke();
        [UIAction("practice-pressed")] private void Practice() => PracticePressed?.Invoke();
        [UIAction("confirm")] private void Confirm() => ConfirmPressed?.Invoke();
        [UIAction("cancel")] private void Cancel() => CancelPressed?.Invoke();
        protected override void DidDeactivate(bool removedFromHierarchy, bool screenSystemDisabling)
        {
            base.DidDeactivate(removedFromHierarchy, screenSystemDisabling);
            if (removedFromHierarchy) { ++_generation; _content?.Cancel(); HideConfirmation(); }
        }
        protected override void OnDestroy()
        {
            ++_generation; _content?.Cancel(); _content?.Dispose();
            if (_maskMaterial != null) UnityEngine.Object.Destroy(_maskMaterial);
            base.OnDestroy();
        }
    }
}

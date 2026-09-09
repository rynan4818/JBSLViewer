using System;
using System.Collections.Generic;
using BeatSaberMarkupLanguage;
using HarmonyLib;
using IPA.Utilities;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using Zenject;

namespace JBSLViewer.Qualifier
{
    public sealed class QualifierRestartUiController : IInitializable, IDisposable
    {
        private readonly IQualifierGameplayHost _host;
        internal static QualifierRestartUiController Instance { get; private set; }
        private readonly Dictionary<Button, Tuple<bool, bool>> _states = new Dictionary<Button, Tuple<bool, bool>>();
        private readonly HashSet<ResultsViewController> _results = new HashSet<ResultsViewController>();
        private readonly Dictionary<ResultsViewController, TextMeshProUGUI> _notices = new Dictionary<ResultsViewController, TextMeshProUGUI>();
        public QualifierRestartUiController(IQualifierGameplayHost host) { _host = host; }
        public void Initialize() { Instance = this; }
        internal void ResultsShown(ResultsViewController results)
        {
            if (_results.Add(results)) results.restartButtonPressedEvent += Restarted;
            SetHidden(results.GetField<Button, ResultsViewController>("_restartButton"), _host.HideResultRestart);
            var notice = _host.HideResultRestart ? null : _host.Notice;
            if (!_notices.TryGetValue(results, out var label) && !string.IsNullOrWhiteSpace(notice))
            {
                label = BeatSaberUI.CreateText(results.transform as RectTransform, string.Empty, Vector2.zero, new Vector2(110, 14));
                label.name = "JBSLQualifierRestartNotice";
                label.alignment = TextAlignmentOptions.Center;
                label.fontSize = 2.3f;
                label.enableWordWrapping = true;
                label.richText = false;
                label.raycastTarget = false;
                label.rectTransform.anchorMin = label.rectTransform.anchorMax = new Vector2(.5f, 0);
                label.rectTransform.pivot = new Vector2(.5f, 0);
                label.rectTransform.anchoredPosition = new Vector2(0, 1);
                _notices.Add(results, label);
            }
            if (label != null)
            {
                label.text = notice ?? string.Empty;
                label.gameObject.SetActive(!string.IsNullOrWhiteSpace(notice));
            }
        }
        private void Restarted(ResultsViewController results)
        { if (_host.HideResultRestart) _host.OrdinaryRestartDetected(); }
        internal void PauseShown(PauseMenuManager pause)
        { SetHidden(pause.GetField<Button, PauseMenuManager>("_restartButton"), QualifierGameplayObserver.Current?.IsChallengeActive == true); }
        private void SetHidden(Button button, bool hidden)
        {
            foreach (var old in new List<Button>(_states.Keys)) if (old == null) _states.Remove(old);
            if (button == null) return;
            if (hidden)
            {
                if (!_states.ContainsKey(button)) _states.Add(button, Tuple.Create(button.gameObject.activeSelf, button.interactable));
                button.interactable = false;
                button.gameObject.SetActive(false);
            }
            else Restore(button);
        }
        private void Restore(Button button)
        {
            if (ReferenceEquals(button, null) || !_states.TryGetValue(button, out var previous)) return;
            _states.Remove(button);
            if (button != null) { button.gameObject.SetActive(previous.Item1); button.interactable = previous.Item2; }
        }
        internal void ResultsHidden(ResultsViewController results)
        {
            Restore(results.GetField<Button, ResultsViewController>("_restartButton"));
            if (_notices.TryGetValue(results, out var label) && label != null) label.gameObject.SetActive(false);
        }
        public void Dispose()
        {
            foreach (var result in _results) if (result != null) result.restartButtonPressedEvent -= Restarted;
            foreach (var button in new List<Button>(_states.Keys)) Restore(button);
            _results.Clear();
            foreach (var label in _notices.Values) if (label != null) UnityEngine.Object.Destroy(label.gameObject);
            _notices.Clear();
            if (Instance == this) Instance = null;
        }
    }
    [HarmonyPatch(typeof(ResultsViewController), "DidActivate")]
    internal static class QualifierResultsShownPatch
    { private static void Postfix(ResultsViewController __instance) { QualifierRestartUiController.Instance?.ResultsShown(__instance); } }
    [HarmonyPatch(typeof(ResultsViewController), "DidDeactivate")]
    internal static class QualifierResultsHiddenPatch
    { private static void Postfix(ResultsViewController __instance) { QualifierRestartUiController.Instance?.ResultsHidden(__instance); } }
    [HarmonyPatch(typeof(PauseMenuManager), nameof(PauseMenuManager.ShowMenu))]
    internal static class QualifierPauseShownPatch
    { private static void Postfix(PauseMenuManager __instance) { QualifierRestartUiController.Instance?.PauseShown(__instance); } }
}

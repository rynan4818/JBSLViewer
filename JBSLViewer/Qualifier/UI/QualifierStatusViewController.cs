/*
Portions copied/adapted from TournamentAssistant.
Source: https://github.com/MatrikMoon/TournamentAssistant?tab=MIT-1-ov-file
Original: TournamentAssistant/UI/ViewControllers/RemainingAttempts.cs
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
using BeatSaberMarkupLanguage.Attributes;
using BeatSaberMarkupLanguage.ViewControllers;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace JBSLViewer.Qualifier.UI
{
    public sealed class QualifierStatusViewController : BSMLAutomaticViewController
    {
        public event Action RetryRequested;
        [UIComponent("text")] private TextMeshProUGUI text;
        [UIComponent("message")] private TextMeshProUGUI message;
        [UIComponent("retry")] private Button retry;
        [UIValue("text-string")] private string _text = "Remaining Attempts: --";
        private string _message = "";
        private int? _remaining;
        private bool _locked;
        public void SetState(int? remaining, int? limit, string detail, bool locked)
        {
            _remaining = remaining;
            _text = "Remaining Attempts: " + (remaining.HasValue ? remaining + " / " + limit : "--");
            _message = detail ?? "";
            _locked = locked;
            Render();
        }
        [UIAction("#post-parse")] private void Render()
        {
            if (text == null) return;
            text.richText = message.richText = false;
            text.text = _text;
            text.color = !_remaining.HasValue ? Color.white : _remaining > 0 ? Color.green : Color.red;
            message.text = _message;
            retry.interactable = !_locked;
        }
        [UIAction("retry")] private void Retry() => RetryRequested?.Invoke();
    }
}

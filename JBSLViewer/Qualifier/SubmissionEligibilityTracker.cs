// Interoperability follows BeatLeader: https://github.com/BeatLeader/beatleader-mod/blob/1291supportx/LICENSE
// Copyright (c) 2023 BeatLeader. MIT License; see THIRD-PARTY-NOTICES.txt in the distribution.
using System;
using System.Collections.Generic;
using System.Linq;
using JBSLViewer.Qualifier.Core;
using SiraUtil.Submissions;
using Zenject;

namespace JBSLViewer.Qualifier
{
    public sealed class SubmissionObservation
    {
        public bool Allowed { get; set; }
        public string[] Blockers { get; set; }
    }

    // App scope: current API state and a separate, explicitly attached play history.
    // Sira's SubmissionDataContainer.Disabled is deliberately never read: it is a
    // completed game's display snapshot, not the state for the next reservation.
    public sealed class SubmissionEligibilityTracker : IInitializable, ITickable, IDisposable
    {
        internal static SubmissionEligibilityTracker Instance { get; private set; }
        private static readonly HashSet<Submission> LiveSubmissions = new HashSet<Submission>();
        private SubmissionHistory _history;
        public event Action StateChanged;
        private string _lastState;
        public void Initialize() { Instance = this; Refresh(); }
        public void Tick() { Refresh(); }

        public SubmissionObservation ReadCurrent()
        {
            var blockers = new List<string>();
            try
            {
                if (BS_Utils.Gameplay.ScoreSubmission.Disabled)
                    blockers.Add("bs_utils:" + BS_Utils.Gameplay.ScoreSubmission.ModString);
                if (BS_Utils.Gameplay.ScoreSubmission.ProlongedDisabled)
                    blockers.Add("bs_utils_prolonged:" + BS_Utils.Gameplay.ScoreSubmission.ProlongedModString);
                foreach (var submission in LiveSubmissions)
                    foreach (var ticket in submission.Tickets())
                    {
                        var reasons = ticket.Reasons();
                        blockers.Add("sirautil:" + (reasons.Length == 0 ? "submission_disabled" : string.Join(";", reasons)));
                    }
            }
            catch (Exception ex)
            {
                blockers.Add("submission_state_unavailable");
                Plugin.Log.Warn("Qualifier submission state unavailable: " + ex.Message);
            }
            return new SubmissionObservation { Allowed = blockers.Count == 0, Blockers = blockers.Distinct().ToArray() };
        }

        // Runtime must call immediately before invoking the standard Play method.
        public void Track(SubmissionHistory history)
        {
            if (_history != null && !ReferenceEquals(_history, history)) throw new InvalidOperationException("Previous play history is still attached.");
            _history = history ?? throw new ArgumentNullException(nameof(history));
            Refresh();
        }
        public void Detach(SubmissionHistory history) { if (ReferenceEquals(_history, history)) _history = null; }
        public void Refresh()
        {
            var state = ReadCurrent();
            _history?.Observe(state.Allowed, state.Blockers);
            var key = string.Join("|", state.Blockers);
            if (_lastState == key) return;
            _lastState = key;
            StateChanged?.Invoke();
        }
        internal static void Register(Submission submission)
        {
            LiveSubmissions.Add(submission);
            Instance?.Refresh();
        }
        internal static void Changed(Submission submission)
        {
            LiveSubmissions.Add(submission);
            Instance?.Refresh();
        }
        internal static void Disposed(Submission submission)
        {
            // Observe remaining blockers before removing the old scene instance.
            Instance?.Refresh();
            LiveSubmissions.Remove(submission);
            Instance?.Refresh();
        }
        internal static void StandardSubmissionObserved(bool allowed, string source)
        {
            // These notifications can be latched by BL. We only latch this play's
            // history, and use the live APIs again for the next menu operation.
            if (!allowed) Instance?._history?.Observe(false, new[] { source });
            Instance?.Refresh();
        }
        public void Dispose() { if (Instance == this) Instance = null; _history = null; }
    }
}

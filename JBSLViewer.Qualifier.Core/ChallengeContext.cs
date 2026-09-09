using System;
using JBSLViewer.Qualifier.Core.Contracts;
namespace JBSLViewer.Qualifier.Core {
    public sealed class ChallengeContext {
        public string ChallengeId { get; set; }
        public int LeagueId { get; set; }
        public string OwnerSid { get; set; }
        public string ScoreServerBaseUrl { get; set; }
        public string ReserveKey { get; set; }
        public string ClientVersion { get; set; }
        public string GameVersion { get; set; } = "1.37.1";
        public string ClientResultId { get; set; } = Guid.NewGuid().ToString();
        public MapKey Map { get; set; }
        public DateTimeOffset ResultAcceptUntil { get; set; }
        public long GameplayGeneration { get; set; }
        public SubmissionHistory Submission { get; set; } = new SubmissionHistory();
        public ResultTiming Timing { get; set; } = new ResultTiming();
        public bool PlayInvoked { get; internal set; }
        public bool Started { get; internal set; }
        public bool Detached { get; internal set; }
        public bool Completed { get; internal set; }
        public bool ResultCleared { get; internal set; }
        internal bool Finalizing { get; set; }
        internal SubmissionEligibility FrozenSubmission { get; set; }
        internal ResultTiming FrozenTiming { get; set; }
    }
}

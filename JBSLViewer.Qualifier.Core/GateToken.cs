using System;
using JBSLViewer.Qualifier.Core.Contracts;
namespace JBSLViewer.Qualifier.Core {
    public sealed class SelectionSnapshot {
        public long SelectionGeneration { get; set; }
        public int LeagueId { get; set; }
        public MapKey Map { get; set; }
        public string CurrentSid { get; set; }
        public bool IsSolo { get; set; }
        public double? LocalSongDurationSeconds { get; set; }
        public double? SongSpeedMultiplier { get; set; }
        public LeaderboardContract Leaderboard { get; set; }
        public bool LeaderboardFresh { get; set; }
        public string SongTitle { get; set; }
    }
    public sealed class GateToken : IEquatable<GateToken> {
        public long SelectionGeneration { get; set; }
        public long AuthenticationGeneration { get; set; }
        public string ScoreServerBaseUrl { get; set; }
        public int LeagueId { get; set; }
        public MapKey Map { get; set; }
        public string CurrentSid { get; set; }
        public string Revision { get; set; }
        public bool IsSolo { get; set; }
        public bool Equals(GateToken x) { return x!=null && SelectionGeneration==x.SelectionGeneration && AuthenticationGeneration==x.AuthenticationGeneration && ScoreServerBaseUrl==x.ScoreServerBaseUrl && LeagueId==x.LeagueId && Equals(Map,x.Map) && CurrentSid==x.CurrentSid && Revision==x.Revision && IsSolo==x.IsSolo; }
    }
    public sealed class QualifierViewState {
        public bool Visible { get; set; }
        public bool CanChallenge { get; set; }
        public bool ConfirmationOpen { get; set; }
        public bool CanConfirm { get; set; }
        public int? RemainingAttempts { get; set; }
        public int? AttemptLimit { get; set; }
        public string Message { get; set; }
    }
}

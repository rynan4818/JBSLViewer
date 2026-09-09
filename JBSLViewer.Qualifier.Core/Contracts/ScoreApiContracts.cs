using System;
using Newtonsoft.Json;
namespace JBSLViewer.Qualifier.Core.Contracts {
    public sealed class AuthResponse {
        [JsonProperty("schemaVersion")] public int SchemaVersion { get; set; }
        [JsonProperty("authenticated")] public bool Authenticated { get; set; }
        [JsonProperty("user")] public AuthUser User { get; set; }
        [JsonProperty("expiresAt")] public DateTimeOffset ExpiresAt { get; set; }
    }
    public sealed class AuthUser { [JsonProperty("sid")] public string Sid { get; set; } [JsonProperty("displayName")] public string DisplayName { get; set; } }
    public sealed class StatusResponse {
        [JsonProperty("schemaVersion")] public int SchemaVersion { get; set; }
        [JsonProperty("serverTime")] public DateTimeOffset ServerTime { get; set; }
        [JsonProperty("eligible")] public bool Eligible { get; set; }
        [JsonProperty("reasonCode")] public string ReasonCode { get; set; }
        [JsonProperty("league")] public StatusLeague League { get; set; }
        [JsonProperty("map")] public StatusMap Map { get; set; }
        [JsonProperty("isParticipant")] public bool? IsParticipant { get; set; }
        [JsonProperty("remainingAttempts")] public int? RemainingAttempts { get; set; }
        [JsonProperty("cache")] public StatusCache Cache { get; set; }
    }
    public sealed class StatusLeague {
        [JsonProperty("id")] public int Id { get; set; }
        [JsonProperty("name")] public string Name { get; set; }
        [JsonProperty("submissionMethod")] public string SubmissionMethod { get; set; }
        [JsonProperty("revision")] public string Revision { get; set; }
    }
    public sealed class StatusMap {
        [JsonProperty("hash")] public string Hash { get; set; }
        [JsonProperty("characteristic")] public string Characteristic { get; set; }
        [JsonProperty("difficulty")] public string Difficulty { get; set; }
        [JsonProperty("title")] public string Title { get; set; }
        [JsonProperty("attemptLimit")] public int? AttemptLimit { get; set; }
        [JsonProperty("attemptScope")] public string AttemptScope { get; set; }
        [JsonIgnore] public MapKey Key { get { return MapKey.Create(Hash, Characteristic, Difficulty); } }
    }
    public sealed class StatusCache { [JsonProperty("fetchedAt")] public DateTimeOffset FetchedAt { get; set; } [JsonProperty("stale")] public bool Stale { get; set; } }
    public sealed class ReserveRequest {
        [JsonProperty("schemaVersion")] public int SchemaVersion { get; set; } = 1;
        [JsonProperty("leagueId")] public int LeagueId { get; set; }
        [JsonProperty("map")] public MapKey Map { get; set; }
        [JsonProperty("clientVersion")] public string ClientVersion { get; set; }
        [JsonProperty("gameVersion")] public string GameVersion { get; set; } = "1.29.1";
    }
    public sealed class ReserveResponse {
        [JsonIgnore] public int ResponseHttpStatus { get; set; }
        [JsonIgnore] public string RawJson { get; set; }
        [JsonProperty("schemaVersion")] public int SchemaVersion { get; set; }
        [JsonProperty("challengeId")] public string ChallengeId { get; set; }
        [JsonProperty("status")] public string Status { get; set; }
        [JsonProperty("attemptNumber")] public int AttemptNumber { get; set; }
        [JsonProperty("attemptLimit")] public int AttemptLimit { get; set; }
        [JsonProperty("remainingAttempts")] public int RemainingAttempts { get; set; }
        [JsonProperty("reservedAt")] public DateTimeOffset ReservedAt { get; set; }
        [JsonProperty("resultAcceptUntil")] public DateTimeOffset ResultAcceptUntil { get; set; }
        [JsonProperty("map")] public MapKey Map { get; set; }
    }
    public sealed class StartedRequest {
        [JsonProperty("schemaVersion")] public int SchemaVersion { get; set; } = 1;
        [JsonProperty("actualMap")] public MapKey ActualMap { get; set; }
        [JsonProperty("gameMode")] public string GameMode { get; set; } = "Solo";
        [JsonProperty("practice")] public bool Practice { get; set; }
        [JsonProperty("submissionAllowed")] public bool SubmissionAllowed { get; set; }
        [JsonProperty("startedAtClient")] public DateTimeOffset StartedAtClient { get; set; }
    }
    public sealed class ResultResponse {
        [JsonIgnore] public string RawJson { get; set; }
        [JsonProperty("schemaVersion")] public int SchemaVersion { get; set; }
        [JsonProperty("submissionId")] public string SubmissionId { get; set; }
        [JsonProperty("challengeId")] public string ChallengeId { get; set; }
        [JsonProperty("status")] public string Status { get; set; }
        [JsonProperty("validForRanking")] public bool ValidForRanking { get; set; }
        [JsonProperty("invalidReason")] public string InvalidReason { get; set; }
        [JsonProperty("receivedAt")] public DateTimeOffset ReceivedAt { get; set; }
        [JsonProperty("replaySha256")] public string ReplaySha256 { get; set; }
        [JsonProperty("remainingAttempts")] public int RemainingAttempts { get; set; }
    }
    public sealed class ResultMetadata {
        [JsonProperty("schemaVersion")] public int SchemaVersion { get; set; } = 1;
        [JsonProperty("clientResultId")] public string ClientResultId { get; set; }
        [JsonProperty("challengeId")] public string ChallengeId { get; set; }
        [JsonProperty("map")] public MapKey Map { get; set; }
        [JsonProperty("endState")] public string EndState { get; set; }
        [JsonProperty("endAction")] public string EndAction { get; set; }
        [JsonProperty("endType")] public string EndType { get; set; }
        [JsonProperty("endSongTime")] public double? EndSongTime { get; set; }
        [JsonProperty("multipliedScore")] public int? MultipliedScore { get; set; }
        [JsonProperty("modifiedScore")] public int? ModifiedScore { get; set; }
        [JsonProperty("maxPossibleModifiedScore")] public int? MaxPossibleModifiedScore { get; set; }
        [JsonProperty("missedCount")] public int? MissedCount { get; set; }
        [JsonProperty("badCutsCount")] public int? BadCutsCount { get; set; }
        [JsonProperty("goodCutsCount")] public int? GoodCutsCount { get; set; }
        [JsonProperty("maxCombo")] public int? MaxCombo { get; set; }
        [JsonProperty("fullCombo")] public bool? FullCombo { get; set; }
        [JsonProperty("energy")] public double? Energy { get; set; }
        [JsonProperty("modifiers")] public string[] Modifiers { get; set; }
        [JsonProperty("submissionEligibility")] public SubmissionEligibility SubmissionEligibility { get; set; } = new SubmissionEligibility();
        [JsonProperty("scoreValidity")] public ScoreValidity ScoreValidity { get; set; } = new ScoreValidity();
        [JsonProperty("diagnostics")] public ResultDiagnostics Diagnostics { get; set; } = new ResultDiagnostics();
        [JsonProperty("timing")] public ResultTiming Timing { get; set; } = new ResultTiming();
        [JsonProperty("clientVersion")] public string ClientVersion { get; set; }
        [JsonProperty("gameVersion")] public string GameVersion { get; set; } = "1.29.1";
    }
    public sealed class SubmissionEligibility {
        [JsonProperty("allowedAtStart")] public bool AllowedAtStart { get; set; }
        [JsonProperty("remainedAllowed")] public bool RemainedAllowed { get; set; }
        [JsonProperty("blockers")] public string[] Blockers { get; set; } = new string[0];
    }
    public sealed class ScoreValidity {
        [JsonProperty("validForRanking")] public bool ValidForRanking { get; set; }
        [JsonProperty("invalidReason")] public string InvalidReason { get; set; }
        [JsonProperty("restartDetected")] public bool RestartDetected { get; set; }
        [JsonProperty("playInstanceCount")] public int PlayInstanceCount { get; set; }
    }
    public sealed class ResultDiagnostics {
        [JsonProperty("failureCode")] public string FailureCode { get; set; }
        [JsonProperty("actualMap")] public MapKey ActualMap { get; set; }
        [JsonProperty("replayGenerationFailed")] public bool? ReplayGenerationFailed { get; set; }
    }
    public sealed class ResultTiming {
        [JsonProperty("confirmedAtClient")] public DateTimeOffset? ConfirmedAtClient { get; set; }
        [JsonProperty("reserveResponseReceivedAtClient")] public DateTimeOffset? ReserveResponseReceivedAtClient { get; set; }
        [JsonProperty("startedAtClient")] public DateTimeOffset? StartedAtClient { get; set; }
        [JsonProperty("endedAtClient")] public DateTimeOffset? EndedAtClient { get; set; }
        [JsonProperty("resultFinalizedAtClient")] public DateTimeOffset? ResultFinalizedAtClient { get; set; }
        [JsonProperty("localSongDurationSeconds")] public double? LocalSongDurationSeconds { get; set; }
        [JsonProperty("songSpeedMultiplier")] public double? SongSpeedMultiplier { get; set; }
        [JsonProperty("totalPauseSeconds")] public double? TotalPauseSeconds { get; set; }
    }
}

using System;
using JBSLViewer.Qualifier.Core.Contracts;
using Newtonsoft.Json;
namespace JBSLViewer.Qualifier.Core.Outbox {
    public sealed class OutboxEntry {
        public string Id { get; set; }
        public string ChallengeId { get; set; }
        public string OwnerSid { get; set; }
        [JsonProperty("scoreServerBaseUrl")] public string ScoreServerBaseUrl { get; set; }
        public string IdempotencyKey { get; set; }
        public string MetadataJson { get; set; }
        public byte[] ReplayGzip { get; set; }
        public DateTimeOffset ResultAcceptUntil { get; set; }
        public string State { get; set; }
        public string StateAfterSave { get; set; }
        [JsonProperty("blockedReason")] public string BlockedReason { get; set; }
        public bool OwnerMismatch { get; set; }
        public string ErrorCode { get; set; }
        public int? HttpStatus { get; set; }
        public string RequestId { get; set; }
        public ResultResponse Response { get; set; }
        public string ResponseJson { get; set; }
        public int RetryCount { get; set; }
        public DateTimeOffset? NextAttemptAt { get; set; }
        public bool Persisted { get; set; }
        public long Generation { get; set; }
    }
}

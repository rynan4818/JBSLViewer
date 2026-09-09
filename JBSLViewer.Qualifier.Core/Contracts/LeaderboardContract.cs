using System;
using System.Collections.Generic;
using Newtonsoft.Json;
namespace JBSLViewer.Qualifier.Core.Contracts {
    public sealed class LeaderboardContract {
        [JsonProperty("league_id")] public int LeagueId { get; set; }
        [JsonProperty("league_title")] public string Title { get; set; }
        [JsonProperty("isLive")] public bool IsLive { get; set; }
        [JsonProperty("isOpen")] public bool IsOpen { get; set; }
        [JsonProperty("end")] public DateTimeOffset End { get; set; }
        [JsonProperty("participants")] public List<Participant> Participants { get; set; }
        [JsonProperty("qualifier")] public QualifierSettings Qualifier { get; set; }
        [JsonProperty("maps")] public List<QualifierMap> Maps { get; set; }
    }
    public sealed class Participant { [JsonProperty("sid")] public string Sid { get; set; } }
    public sealed class QualifierSettings {
        [JsonProperty("enabled")] public bool Enabled { get; set; }
        [JsonProperty("submission_method")] public string SubmissionMethod { get; set; }
        [JsonProperty("revision")] public string Revision { get; set; }
        [JsonProperty("starts_at")] public DateTimeOffset? StartsAt { get; set; }
        [JsonProperty("ends_at")] public DateTimeOffset? EndsAt { get; set; }
    }
    public sealed class QualifierMap {
        [JsonProperty("hash")] public string Hash { get; set; }
        [JsonProperty("characteristic")] public string Characteristic { get; set; }
        [JsonProperty("difficulty")] public string Difficulty { get; set; }
        [JsonProperty("title")] public string Title { get; set; }
        [JsonProperty("song_duration_seconds")] public double? SongDurationSeconds { get; set; }
        [JsonProperty("qualifier_attempt_limit")] public int? AttemptLimit { get; set; }
        [JsonIgnore] public MapKey Key { get { return MapKey.Create(Hash, Characteristic, Difficulty); } }
    }
}

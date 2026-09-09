using System;
using System.Linq;
using System.Text.RegularExpressions;
using Newtonsoft.Json;

namespace JBSLViewer.Qualifier.Core.Contracts {
    public sealed class MapKey : IEquatable<MapKey> {
        [JsonProperty("hash")] public string Hash { get; set; }
        [JsonProperty("characteristic")] public string Characteristic { get; set; }
        [JsonProperty("difficulty")] public string Difficulty { get; set; }
        public static MapKey Create(string hash, string characteristic, string difficulty) {
            hash = (hash ?? "").Trim().ToUpperInvariant();
            if (difficulty == "Expert+" || difficulty == "Expert Plus") difficulty = "ExpertPlus";
            if (!Regex.IsMatch(hash, "\\A[0-9A-F]{40}\\z") || !new[] {"Standard","OneSaber","NoArrows","360Degree","90Degree","Lawless","Lightshow"}.Contains(characteristic) || !new[] {"Easy","Normal","Hard","Expert","ExpertPlus"}.Contains(difficulty)) throw new FormatException("Invalid MapKey");
            return new MapKey { Hash = hash, Characteristic = characteristic, Difficulty = difficulty };
        }
        public MapKey Copy() { return Create(Hash, Characteristic, Difficulty); }
        public bool Equals(MapKey other) { return other != null && Hash == other.Hash && Characteristic == other.Characteristic && Difficulty == other.Difficulty; }
        public override bool Equals(object obj) { return Equals(obj as MapKey); }
        public override int GetHashCode() { return (Hash + "|" + Characteristic + "|" + Difficulty).GetHashCode(); }
        public override string ToString() { return Hash + "/" + Characteristic + "/" + Difficulty; }
    }
}

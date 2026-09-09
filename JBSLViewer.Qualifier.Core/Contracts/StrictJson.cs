using System;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
namespace JBSLViewer.Qualifier.Core.Contracts {
    public static class StrictJson {
        public static readonly JsonSerializerSettings Settings = new JsonSerializerSettings { NullValueHandling = NullValueHandling.Include, DateParseHandling = DateParseHandling.None, DateTimeZoneHandling = DateTimeZoneHandling.Utc, Formatting = Formatting.None };
        public static string Serialize(object value) { return JsonConvert.SerializeObject(value, Settings); }
        public static T Clone<T>(T value) { return JsonConvert.DeserializeObject<T>(Serialize(value), Settings); }
        public static JObject Object(string json) {
            using(var tokens=new JsonTextReader(new StringReader(json)) {DateParseHandling=DateParseHandling.None,MaxDepth=64}) {
                var objects=new Stack<HashSet<string>>();
                while(tokens.Read()) {
                    if(tokens.TokenType==JsonToken.Comment) throw new FormatException("JSON comments are not permitted");
                    if(tokens.TokenType==JsonToken.StartObject) objects.Push(new HashSet<string>(StringComparer.Ordinal));
                    if(tokens.TokenType==JsonToken.EndObject) objects.Pop();
                    if(tokens.TokenType==JsonToken.PropertyName && !objects.Peek().Add((string)tokens.Value)) throw new FormatException("Duplicate JSON property");
                    if(tokens.TokenType==JsonToken.Float) { var number=Convert.ToDouble(tokens.Value,CultureInfo.InvariantCulture);if(double.IsNaN(number)||double.IsInfinity(number)) throw new FormatException("Non-finite JSON number"); }
                }
            }
            using (var reader = new JsonTextReader(new StringReader(json)) { DateParseHandling = DateParseHandling.None, MaxDepth = 64 }) {
                var result = JObject.Load(reader);
                if (reader.Read()) throw new FormatException("Trailing JSON content");
                return result;
            }
        }
        public static JToken Require(JObject obj, string name, JTokenType type, bool nullable = false) {
            var t = obj[name];
            if (t == null || (t.Type != type && !(nullable && t.Type == JTokenType.Null))) throw new FormatException("Invalid field: " + name);
            return t;
        }
        public static int Integer(JObject obj, string name, int min = 0, bool nullable = false) {
            var t = Require(obj, name, JTokenType.Integer, nullable);
            if (t.Type == JTokenType.Null) return min;
            var n = t.Value<long>(); if (n < min || n > int.MaxValue) throw new FormatException("Invalid integer: " + name); return (int)n;
        }
        public static string String(JObject obj, string name, bool nullable = false) { var t = Require(obj,name,JTokenType.String,nullable); return t.Type == JTokenType.Null ? null : t.Value<string>(); }
        public static void Date(JObject obj,string name,bool nullable = false) {
            var s = String(obj,name,nullable); DateTimeOffset value;
            if (s != null && (!Regex.IsMatch(s,@"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)\z") || !DateTimeOffset.TryParse(s,CultureInfo.InvariantCulture,DateTimeStyles.RoundtripKind,out value))) throw new FormatException("Invalid UTC timestamp: " + name);
        }
        private static MapKey Map(JObject obj) { return MapKey.Create(String(obj,"hash"),String(obj,"characteristic"),String(obj,"difficulty")); }
        private static void Schema(JObject obj) { if (Integer(obj,"schemaVersion",1) != 1) throw new FormatException("Unsupported schema"); }
        public static LeaderboardContract ParseLeaderboard(string json) {
            var o = Object(json); Integer(o,"league_id",1); String(o,"league_title"); Require(o,"isLive",JTokenType.Boolean); Require(o,"isOpen",JTokenType.Boolean); Date(o,"end");
            var q = (JObject)Require(o,"qualifier",JTokenType.Object); Require(q,"enabled",JTokenType.Boolean); String(q,"submission_method"); if (string.IsNullOrWhiteSpace(String(q,"revision"))) throw new FormatException("Invalid revision"); Date(q,"starts_at",true); Date(q,"ends_at",true);
            foreach (var p in (JArray)Require(o,"participants",JTokenType.Array)) { if (!(p is JObject)) throw new FormatException("Invalid participant"); var sid = String((JObject)p,"sid"); if (string.IsNullOrWhiteSpace(sid) || sid.Trim()!=sid) throw new FormatException("Invalid sid"); }
            foreach (var m in (JArray)Require(o,"maps",JTokenType.Array)) {
                var map = m as JObject; if (map == null) throw new FormatException("Invalid map"); Map(map); String(map,"title");
                Integer(map,"qualifier_attempt_limit",1,true); if (map["qualifier_attempt_limit"].Type != JTokenType.Null && map["qualifier_attempt_limit"].Value<long>()>100) throw new FormatException("Invalid limit");
                var duration=map["song_duration_seconds"]; if (duration==null || (duration.Type != JTokenType.Null && duration.Type != JTokenType.Float && duration.Type != JTokenType.Integer)) throw new FormatException("Invalid duration");
                if (duration.Type != JTokenType.Null && !FinitePositive(duration.Value<double>())) throw new FormatException("Invalid duration");
            }
            var result = o.ToObject<LeaderboardContract>(JsonSerializer.Create(Settings));
            if (result.Participants.GroupBy(p=>p.Sid,StringComparer.Ordinal).Any(g=>g.Count()!=1) || result.Maps.GroupBy(m=>m.Key).Any(g=>g.Count()!=1)) throw new FormatException("Duplicate identity or MapKey");
            return result;
        }
        public static bool TryParseLeaderboard(string json,out LeaderboardContract result,out string error) { try { result=ParseLeaderboard(json); error=null; return true; } catch(Exception ex) { result=null; error=ex.Message; return false; } }
        public static AuthResponse ParseAuth(string json) { var o=Object(json); Schema(o); Require(o,"authenticated",JTokenType.Boolean); Date(o,"expiresAt"); var u=(JObject)Require(o,"user",JTokenType.Object); String(u,"sid"); return o.ToObject<AuthResponse>(JsonSerializer.Create(Settings)); }
        public static StatusResponse ParseStatus(string json) {
            var o=Object(json); Schema(o); Date(o,"serverTime"); Require(o,"eligible",JTokenType.Boolean); String(o,"reasonCode"); Require(o,"isParticipant",JTokenType.Boolean,true); Integer(o,"remainingAttempts",0,true);
            var league=Require(o,"league",JTokenType.Object,true) as JObject; if(league!=null) { Integer(league,"id",1); String(league,"name",true); String(league,"submissionMethod",true); String(league,"revision",true); }
            var map=Require(o,"map",JTokenType.Object,true) as JObject; if(map!=null) { Map(map); String(map,"title",true); Integer(map,"attemptLimit",1,true); if(String(map,"attemptScope")!="per_player_per_map") throw new FormatException("Invalid scope"); }
            var cache=(JObject)Require(o,"cache",JTokenType.Object); Date(cache,"fetchedAt"); Require(cache,"stale",JTokenType.Boolean);
            return o.ToObject<StatusResponse>(JsonSerializer.Create(Settings));
        }
        public static ReserveResponse ParseReserve(string json) {
            var o=Object(json); Schema(o); Guid id; if(!Guid.TryParse(String(o,"challengeId"),out id)) throw new FormatException("Invalid challengeId"); if(String(o,"status")!="reserved") throw new FormatException("Invalid reserve state"); Integer(o,"attemptNumber",1); Integer(o,"attemptLimit",1); Integer(o,"remainingAttempts"); Date(o,"reservedAt"); Date(o,"resultAcceptUntil"); Map((JObject)Require(o,"map",JTokenType.Object)); return o.ToObject<ReserveResponse>(JsonSerializer.Create(Settings));
        }
        public static ResultResponse ParseResult(string json) {
            var o=Object(json); Schema(o); String(o,"submissionId"); String(o,"challengeId"); if(String(o,"status")!="submitted") throw new FormatException("Invalid result state"); Require(o,"validForRanking",JTokenType.Boolean); String(o,"invalidReason",true); Date(o,"receivedAt"); String(o,"replaySha256",true); Integer(o,"remainingAttempts"); return o.ToObject<ResultResponse>(JsonSerializer.Create(Settings));
        }
        public static bool FinitePositive(double n) { return n > 0 && !double.IsNaN(n) && !double.IsInfinity(n); }
    }
}

using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using JBSLViewer.Models;
using JBSLViewer.Qualifier.Core;
using JBSLViewer.Qualifier.Core.Contracts;
using Newtonsoft.Json.Linq;

// Only infrastructure around the linked production cache is replaced in this assembly.
namespace JBSLViewer { internal static class Plugin { public static TestLog Log=new TestLog(); } internal sealed class TestLog { public int Errors;public void Error(string message) { Errors++; } public void Warn(string message) { } public void Info(string message) { } } }
namespace JBSLViewer.Configuration { internal sealed class PluginConfig { public static PluginConfig Instance=new PluginConfig();public string leaderboardApiUrl="http://cache-test/leaderboard/"; } }
namespace JBSLViewer.Util { internal static class HttpUtility { public static Func<string,Task<string>> Fetch;public static Task<string> GetHttpContentAsync(string url) { return Fetch(url); } } }
namespace JBSLViewer.Models { public sealed class LatestUpdate { public DateTime _latest=DateTime.MinValue; } }

namespace JBSLViewer.Qualifier.Tests {
    internal static class LeaderboardCacheScenarios {
        private static string Fixture(int id) {
            var selection=Rig.Selection(DateTimeOffset.UtcNow,"76561198000000000");selection.Leaderboard.LeagueId=id;
            selection.Leaderboard.Maps.Add(new QualifierMap {Hash=new string('B',40),Characteristic="Standard",Difficulty="Expert",Title="B",AttemptLimit=2,SongDurationSeconds=120});
            var json=StrictJson.Object(StrictJson.Serialize(selection.Leaderboard));json["total_rank"]=new JArray();
            foreach(JObject map in (JArray)json["maps"]) map["scores"]=new JArray(new JObject { ["sid"]="76561198000000000",["miss"]=7,["standing"]=1 });
            return json.ToString();
        }
        public static async Task Run() {
            var latest=new LatestUpdate();var cache=new Leaderboard(latest);int requests=0;var first=new TaskCompletionSource<string>();var second=new TaskCompletionSource<string>();
            JBSLViewer.Util.HttpUtility.Fetch=url=>{requests++;return url.EndsWith("3023")?first.Task:second.Task;};
            var parallel=Enumerable.Range(0,25).Select(i=>cache.GetLeaderboardAsync(3023)).ToArray();Program.Check(requests==1 && parallel.All(t=>ReferenceEquals(t,parallel[0])),"production cache coalesces 25 same-league fetches into one task");
            var other=cache.GetLeaderboardAsync(3024);Program.Check(requests==2,"production cache allows another league to fetch concurrently");
            second.SetResult(Fixture(3024));await other;Program.Check(cache.GetLeaderboardData(3024)!=null && !parallel[0].IsCompleted,"production other-league fetch completes independently");first.SetResult(Fixture(3023));await Task.WhenAll(parallel);
            var board=cache.GetLeaderboardData(3023);Program.Check(cache.IsQualifierCacheFresh(3023) && board.qualifierContract!=null && board.maps[0].scores[0].miss==7,"production cache preserves miss and strict qualifier projection");
            Program.Check(StrictJson.ParseLeaderboard(board.qualifierSourceJson).LeagueId==3023,"production cache retains raw JSON for strict independent validation");
            var selection=Rig.Selection(DateTimeOffset.UtcNow,"76561198000000000");selection.Leaderboard=board.qualifierContract;selection.LeaderboardFresh=cache.IsQualifierCacheFresh(3023);var evaluator=new QualifierEligibilityEvaluator();
            foreach(var index in new[]{0,1,0}) { selection.Map=board.qualifierContract.Maps[index].Key;selection.SelectionGeneration++;Program.Check(evaluator.Evaluate(selection,DateTimeOffset.UtcNow),"production cached map selection "+index+" passes local gate");await cache.GetLeaderboardAsync(3023); }
            Program.Check(requests==2,"production A-B-A map selections add zero WEB requests");
            JBSLViewer.Util.HttpUtility.Fetch=url=>{requests++;return Task.FromResult(Fixture(int.Parse(url.Substring(url.LastIndexOf('/')+1))));};await cache.GetLeaderboardAsync(3023,true);Program.Check(requests==3,"production explicit Reload adds one WEB request");
            latest._latest=cache.GetLeaderboardData(3023).jbslViewerGetTime.AddTicks(1);await cache.GetLeaderboardAsync(3023);Program.Check(requests==4,"production LatestUpdate invalidation adds one WEB request");
            var previous=cache.GetLeaderboardData(3023);JBSLViewer.Util.HttpUtility.Fetch=url=>{requests++;return Task.FromResult<string>(null);};await cache.GetLeaderboardAsync(3023,true);Program.Check(!cache.IsQualifierCacheFresh(3023) && ReferenceEquals(previous,cache.GetLeaderboardData(3023)),"production failed refresh keeps display data but blocks new qualifier challenges");
            JBSLViewer.Util.HttpUtility.Fetch=url=>Task.FromResult(Fixture(3023).Replace("\"league_id\": 3023","\"league_id\": \"3023\""));await cache.GetLeaderboardAsync(3023,true);Program.Check(cache.GetLeaderboardData(3023).qualifierContract==null && cache.GetLeaderboardData(3023).qualifierValidationError!=null,"production legacy display cannot authorize malformed qualifier JSON");
        }
    }
}

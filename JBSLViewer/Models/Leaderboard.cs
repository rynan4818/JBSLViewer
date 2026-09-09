using System;
using System.Threading.Tasks;
using System.Collections.Generic;
using System.Collections.Concurrent;
using System.Linq;
using Newtonsoft.Json;
using JBSLViewer.Configuration;
using JBSLViewer.Util;
using JBSLViewer.Models.JBSL;
using JBSLViewer.Qualifier.Core.Contracts;

namespace JBSLViewer.Models
{
    public class Leaderboard
    {
        private readonly LatestUpdate _latestUpdate;
        public bool _getActive = false;
        public ConcurrentDictionary<int, LeaderboardJson> _leaderboards = new ConcurrentDictionary<int, LeaderboardJson>();
        private readonly object _fetchLock = new object();
        private readonly Dictionary<int, Task> _fetches = new Dictionary<int, Task>();
        private readonly HashSet<int> _failedFetches = new HashSet<int>();
        public event Action<int> Updated;
        public Leaderboard(LatestUpdate latestUpdate)
        {
            this._latestUpdate = latestUpdate;
        }
        public Task GetLeaderboardAsync(int leagueID, bool reload = false)
        {
            if (leagueID <= 0) return Task.CompletedTask;
            TaskCompletionSource<bool> completion;
            lock (_fetchLock)
            {
                if (_fetches.TryGetValue(leagueID, out var existing)) return existing;
                if (!reload && IsQualifierCacheFresh(leagueID)) return Task.CompletedTask;
                completion = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
                _fetches.Add(leagueID, completion.Task);
                _getActive = true;
            }
            _ = FetchLeaderboardAsync(leagueID, completion);
            return completion.Task;
        }

        public bool IsQualifierCacheFresh(int leagueID)
        {
            lock (_fetchLock)
                return !_failedFetches.Contains(leagueID) && !_fetches.ContainsKey(leagueID)
                    && _leaderboards.TryGetValue(leagueID, out var value)
                    && value.jbslViewerGetTime >= _latestUpdate._latest;
        }

        private async Task FetchLeaderboardAsync(int leagueID, TaskCompletionSource<bool> completion)
        {
            try
            {
                var resJsonString = await HttpUtility.GetHttpContentAsync($"{PluginConfig.Instance.leaderboardApiUrl}{leagueID}");
                if (resJsonString == null)
                    throw new Exception("JBSL Leaderboard get error");
                var leaderboard = JsonConvert.DeserializeObject<LeaderboardJson>(resJsonString);
                if (leaderboard == null)
                    throw new Exception("JBSL Leaderboard deserialize error");
                leaderboard.qualifierSourceJson = resJsonString;
                try { leaderboard.qualifierContract = StrictJson.ParseLeaderboard(resJsonString); }
                catch (Exception) { leaderboard.qualifierValidationError = "invalid_qualifier_contract"; }
                leaderboard.jbslViewerGetTime = DateTime.Now;
                _leaderboards[leagueID] = leaderboard;
                lock (_fetchLock) _failedFetches.Remove(leagueID);
            }
            catch (Exception ex)
            {
                Plugin.Log.Error(ex.ToString());
                lock (_fetchLock) _failedFetches.Add(leagueID);
            }
            finally
            {
                lock (_fetchLock) { _fetches.Remove(leagueID); _getActive = _fetches.Count != 0; }
                completion.TrySetResult(true);
                Updated?.Invoke(leagueID);
            }
        }
        public string GetLeaderboardName(int leagueID, int index)
        {
            if (!_leaderboards.TryGetValue(leagueID, out var board) || board.maps == null || index < 0 || index >= board.maps.Count)
                return null;
            return this._leaderboards[leagueID].maps[index].title;
        }
        public List<Score> GetMapLeaderboard(int leagueID, int index)
        {
            if (!_leaderboards.TryGetValue(leagueID, out var board) || board.maps == null || index < 0 || index >= board.maps.Count)
                return null;
            return this._leaderboards[leagueID].maps[index].scores;
        }
        public List<Score> GetTotalLeaderboard(int leagueID)
        {
            if (leagueID == -1 || !this._leaderboards.ContainsKey(leagueID))
                return null;
            return this._leaderboards[leagueID].total_rank;
        }
        public List<Map> GetMap(int leagueID)
        {
            if (leagueID == -1 || !this._leaderboards.ContainsKey(leagueID))
                return null;
            return this._leaderboards[leagueID].maps;
        }

        public LeaderboardJson GetLeaderboardData(int leagueID)
        {
            if (leagueID == -1 || !this._leaderboards.ContainsKey(leagueID))
                return null;
            return this._leaderboards[leagueID];
        }

        public LeaderboardValidityContext BuildValidityContext(int leagueID, int maxValid)
        {
            if (leagueID == -1 || !this._leaderboards.ContainsKey(leagueID))
                return new LeaderboardValidityContext();
            return this.BuildValidityContext(this._leaderboards[leagueID], maxValid);
        }

        public LeaderboardValidityContext BuildValidityContext(LeaderboardJson leaderboard, int maxValid)
        {
            var context = new LeaderboardValidityContext();
            if (leaderboard == null || maxValid < 0)
                return context;

            var maps = leaderboard.maps;
            if (maps == null || maps.Count == 0)
                return context;

            var scoreMap = new Dictionary<string, List<LeaderboardMapScoreContext>>(StringComparer.Ordinal);
            for (var mapIndex = 0; mapIndex < maps.Count; mapIndex++)
            {
                var map = maps[mapIndex];
                if (map?.scores == null)
                    continue;

                foreach (var score in map.scores)
                {
                    if (score == null || string.IsNullOrEmpty(score.sid))
                        continue;

                    if (!scoreMap.TryGetValue(score.sid, out var scores))
                    {
                        scores = new List<LeaderboardMapScoreContext>();
                        scoreMap.Add(score.sid, scores);
                    }

                    scores.Add(new LeaderboardMapScoreContext(mapIndex, map.title, score));
                }
            }

            foreach (var scorePair in scoreMap)
            {
                var orderedScores = scorePair.Value
                    .OrderByDescending(x => x.Score.pos)
                    .ThenByDescending(x => x.Score.acc)
                    .Take(maxValid)
                    .ToList();

                var summary = new PlayerValiditySummary
                {
                    ValidCount = orderedScores.Count,
                    PosTooltip = BuildTooltip(orderedScores, x => $"{FormatTooltipTitle(x.MapTitle)} ({x.Score.pos})"),
                    ValidTooltip = BuildTooltip(orderedScores, x => FormatTooltipTitle(x.MapTitle)),
                    AccTooltip = BuildTooltip(orderedScores, x => $"{FormatTooltipTitle(x.MapTitle)} ({x.Score.acc:F2})"),
                };

                context.PlayerSummaries[scorePair.Key] = summary;
                foreach (var validScore in orderedScores)
                    context.ValidScoreKeys.Add(LeaderboardValidityContext.CreateScoreKey(validScore.MapIndex, scorePair.Key));
            }

            return context;
        }

        public static int InferLeagueBasePosFromMaps(LeaderboardJson leaderboard)
        {
            var inferredBasePos = 0;
            if (leaderboard?.maps != null)
            {
                foreach (var map in leaderboard.maps)
                {
                    if (map?.scores == null || map.scores.Count <= 0)
                        continue;
                    // slope(1) == 0, so the first-place pos is equivalent to league.player.count() + 3.
                    if (map.scores[0] != null && map.scores[0].pos > inferredBasePos)
                        inferredBasePos = map.scores[0].pos;
                }
            }

            return inferredBasePos;
        }

        public static int BuildTotalMaxPos(int basePos, int maxValid)
        {
            if (basePos <= 0 || maxValid <= 0)
                return 0;
            return maxValid * basePos;
        }

        private static string BuildTooltip(IEnumerable<LeaderboardMapScoreContext> scores, Func<LeaderboardMapScoreContext, string> selector)
        {
            if (scores == null)
                return null;

            var tooltipLines = scores.Select(selector).Where(x => !string.IsNullOrEmpty(x)).ToList();
            if (tooltipLines.Count == 0)
                return null;

            return string.Join(Environment.NewLine, tooltipLines);
        }

        private static string FormatTooltipTitle(string title)
        {
            var truncatedTitle = title ?? string.Empty;
            if (truncatedTitle.Length > 25)
                truncatedTitle = truncatedTitle.Substring(0, 25);
            return truncatedTitle + "...";
        }
    }

    public class LeaderboardValidityContext
    {
        public Dictionary<string, PlayerValiditySummary> PlayerSummaries { get; } = new Dictionary<string, PlayerValiditySummary>(StringComparer.Ordinal);
        public HashSet<string> ValidScoreKeys { get; } = new HashSet<string>(StringComparer.Ordinal);

        public bool IsValidScore(int mapIndex, string sid)
        {
            return !string.IsNullOrEmpty(sid) && this.ValidScoreKeys.Contains(CreateScoreKey(mapIndex, sid));
        }

        public bool TryGetSummary(string sid, out PlayerValiditySummary summary)
        {
            if (string.IsNullOrEmpty(sid))
            {
                summary = null;
                return false;
            }

            return this.PlayerSummaries.TryGetValue(sid, out summary);
        }

        public static string CreateScoreKey(int mapIndex, string sid)
        {
            return $"{mapIndex}:{sid}";
        }
    }

    public class PlayerValiditySummary
    {
        public int ValidCount { get; set; }
        public string PosTooltip { get; set; }
        public string ValidTooltip { get; set; }
        public string AccTooltip { get; set; }
    }

    internal sealed class LeaderboardMapScoreContext
    {
        public int MapIndex { get; }
        public string MapTitle { get; }
        public Score Score { get; }

        public LeaderboardMapScoreContext(int mapIndex, string mapTitle, Score score)
        {
            this.MapIndex = mapIndex;
            this.MapTitle = mapTitle;
            this.Score = score;
        }
    }
}

using System;
using System.Threading.Tasks;
using System.Collections.Generic;
using System.Collections.Concurrent;
using System.Linq;
using Newtonsoft.Json;
using JBSLViewer.Configuration;
using JBSLViewer.Util;
using JBSLViewer.Models.JBSL;

namespace JBSLViewer.Models
{
    public class Leaderboard
    {
        private readonly LatestUpdate _latestUpdate;
        public bool _getActive = false;
        public ConcurrentDictionary<int, LeaderboardJson> _leaderboards = new ConcurrentDictionary<int, LeaderboardJson>();
        public Leaderboard(LatestUpdate latestUpdate)
        {
            this._latestUpdate = latestUpdate;
        }
        public async Task GetLeaderboardAsync(int leagueID, bool reload = false)
        {
            if (leagueID == -1 || this._getActive)
                return;
            if (!reload && this._leaderboards.ContainsKey(leagueID) && this._latestUpdate._latest < this._leaderboards[leagueID].jbslViewerGetTime)
                return;
            this._getActive = true;
            LeaderboardJson leaderboard;
            try
            {
                var resJsonString = await HttpUtility.GetHttpContentAsync($"{PluginConfig.Instance.leaderboardApiUrl}{leagueID}");
                if (resJsonString == null)
                    throw new Exception("JBSL Leaderboard get error");
                leaderboard = JsonConvert.DeserializeObject<LeaderboardJson>(resJsonString);
                if (leaderboard == null)
                    throw new Exception("JBSL Leaderboard deserialize error");
            }
            catch (Exception ex)
            {
                Plugin.Log.Error(ex.ToString());
                this._getActive = false;
                return;
            }
            leaderboard.jbslViewerGetTime = DateTime.Now;
            if (this._leaderboards.ContainsKey(leagueID))
                this._leaderboards[leagueID] = leaderboard;
            else
                this._leaderboards.TryAdd(leagueID, leaderboard);
            this._getActive = false;
            return;
        }
        public string GetLeaderboardName(int leagueID, int index)
        {
            if (leagueID == -1 || !this._leaderboards.ContainsKey(leagueID) || index < 0 || index >= this._leaderboards[leagueID].maps.Count)
                return null;
            return this._leaderboards[leagueID].maps[index].title;
        }
        public List<Score> GetMapLeaderboard(int leagueID, int index)
        {
            if (leagueID == -1 || !this._leaderboards.ContainsKey(leagueID) || index < 0 || index >= this._leaderboards[leagueID].maps.Count)
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

        public LeaderboardValidityContext BuildValidityContext(int leagueID, int maxValid)
        {
            var context = new LeaderboardValidityContext();
            if (leagueID == -1 || maxValid < 0 || !this._leaderboards.ContainsKey(leagueID))
                return context;

            var maps = this._leaderboards[leagueID].maps;
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

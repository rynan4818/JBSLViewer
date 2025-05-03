using System;
using System.Threading.Tasks;
using System.Collections.Generic;
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
        public Dictionary<int, LeaderboardJson> _leaderboards = new Dictionary<int, LeaderboardJson>();
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
                this._leaderboards.Add(leagueID, leaderboard);
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
    }
}

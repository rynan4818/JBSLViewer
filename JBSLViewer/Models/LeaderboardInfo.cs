using System;
using System.Linq;
using System.Threading.Tasks;
using System.Collections.Concurrent;
using System.Text.RegularExpressions;
using Newtonsoft.Json;
using JBSLViewer.Configuration;
using JBSLViewer.Util;
using JBSLViewer.Models.ScoreSaber;

namespace JBSLViewer.Models
{
    public class LeaderboardInfo
    {
        private readonly SaveData _saveData;
        private readonly Leaderboard _leaderboard;
        public bool _getActive = false;
        public ConcurrentDictionary<string, LeaderboardInfoJson> LeaderboardInfos { get; set; } = new ConcurrentDictionary<string, LeaderboardInfoJson>();
        public LeaderboardInfo(SaveData saveData, Leaderboard leaderboard)
        {
            this._saveData = saveData;
            this._leaderboard = leaderboard;
        }
        public async Task<LeaderboardInfoJson> GetLeaderboardInfoAsync(string lid)
        {
            if (lid == null || this._getActive)
                return null;
            this._getActive = true;
            LeaderboardInfoJson leaderboardInfo;
            try
            {
                var resJsonString = await HttpUtility.GetHttpContentAsync($"{PluginConfig.Instance.leaderboardInfoUrlHeader}{lid}{PluginConfig.Instance.leaderboardInfoUrlFooter}");
                if (resJsonString == null)
                    throw new Exception("ScoreSaber LeaderboardInfo get error");
                leaderboardInfo = JsonConvert.DeserializeObject<LeaderboardInfoJson>(resJsonString);
                if (leaderboardInfo == null)
                    throw new Exception("ScoreSaber LeaderboardInfo deserialize error");
            }
            catch (Exception ex)
            {
                Plugin.Log.Error(ex.ToString());
                this._getActive = false;
                return null;
            }
            this.AddLeaderboardInfo(lid, leaderboardInfo);
            this._saveData.AddLeaderboardInfo(lid, leaderboardInfo);
            this._getActive = false;
            await Task.Delay(300);
            return leaderboardInfo;
        }
        public void AddLeaderboardInfo(string lid, LeaderboardInfoJson leaderboardInfoData)
        {
            if (lid == null || leaderboardInfoData == null)
                return;
            if (this.LeaderboardInfos.ContainsKey(lid))
                this.LeaderboardInfos[lid] = leaderboardInfoData;
            else
                this.LeaderboardInfos.TryAdd(lid, leaderboardInfoData);
        }

        public async Task SetLeagueMapDataAsync(int leagueId)
        { 
            var maps = this._leaderboard.GetMap(leagueId);
            if (maps == null)
                return;
            var lidHashs = maps.Select(x => (x.lid, x.hash)).ToList();
            var save = false;
            foreach (var (lid, hash) in lidHashs)
            {
                if (hash != null && Regex.IsMatch(hash, "[0-9A-F]{40}", RegexOptions.IgnoreCase))
                    continue;
                if (lid == null || this.LeaderboardInfos.ContainsKey(lid))
                    continue;
                await this.GetLeaderboardInfoAsync(lid);
                save = true;
            }
            if (save)
                await this._saveData.WriteSaveDataAsync();
        }
        public string GetSongHash(string lid)
        {
            if (!this.LeaderboardInfos.TryGetValue(lid, out var leaderboardInfo))
                this._saveData._saveData.LeaderboardInfos.TryGetValue(lid, out leaderboardInfo);
            if (leaderboardInfo == null)
                return null;
            return leaderboardInfo.songHash;
        }
    }
}

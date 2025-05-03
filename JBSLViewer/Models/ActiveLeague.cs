using System;
using System.Threading.Tasks;
using System.Collections.Generic;
using Newtonsoft.Json;
using JBSLViewer.Configuration;
using JBSLViewer.Util;
using JBSLViewer.Models.JBSL;

namespace JBSLViewer.Models
{
    public class ActiveLeague
    {
        private bool _getActive = false;
        public List<LeagueJson> _leagues { get; private set; }
        public DateTime _getTime { get; private set; }

        public async Task GetActiveLeagueAsync()
        {
            if (this._getActive)
                return;
            this._getActive = true;
            try
            {
                var resJsonString = await HttpUtility.GetHttpContentAsync(PluginConfig.Instance.activeLeagueApiUrl);
                if (resJsonString == null)
                    throw new Exception("JBSL Active League get error");
                this._leagues = JsonConvert.DeserializeObject<List<LeagueJson>>(resJsonString);
                if (this._leagues == null)
                    throw new Exception("JBSL Active League deserialize error");
            }
            catch (Exception ex)
            {
                Plugin.Log.Error(ex.ToString());
                this._getActive = false;
                return;
            }
            this._leagues.Sort((a, b) => b.id.CompareTo(a.id));
            this._getTime = DateTime.Now;
            this._getActive = false;
            return;
        }
        public string GetLeagueName(int leagueID)
        {
            if (this._leagues == null || this._leagues.Count <= 0 || leagueID < 0 || this._leagues.FindIndex(x => x.id == leagueID) == -1)
                return null;
            return this._leagues.Find(x => x.id == leagueID).name;
        }
        public int GetLeagueID(int index)
        {
            if (this._leagues == null || this._leagues.Count <= 0 || index < 0 || index >= this._leagues.Count)
                return -1;
            return this._leagues[index].id;
        }
        public int GetLeagueIndex(int leagueID)
        {
            if (this._leagues == null || this._leagues.Count <= 0)
                return -1;
            return this._leagues.FindIndex(x => x.id == leagueID);
        }
    }
}
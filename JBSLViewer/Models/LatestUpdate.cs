using System;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using JBSLViewer.Configuration;
using JBSLViewer.Util;

namespace JBSLViewer.Models
{
    public class LatestUpdate
    {
        private bool _init = false;
        private bool _getActive = false;
        public DateTime _latest { get; private set; }

        public async Task GetHeadlineAsync()
        {
            if (this._getActive)
                return;
            this._getActive = true;
            this._init = true;
            string resHTMLString;
            try
            {
                resHTMLString = await HttpUtility.GetHttpContentAsync(PluginConfig.Instance.headlinesUrl);
                if (resHTMLString == null)
                    throw new Exception("JBSL Headline get error");
            }
            catch (Exception ex)
            {
                Plugin.Log.Error(ex.ToString());
                this._getActive = false;
                return;
            }
            var latestString = Regex.Match(resHTMLString, PluginConfig.Instance.headlineLatest, RegexOptions.Singleline);
            if (latestString.Groups.Count < 5)
            {
                this._getActive = false;
                return;
            }
            var year = latestString.Groups[1].Value;
            var month = latestString.Groups[2].Value;
            var day = latestString.Groups[3].Value;
            var time = latestString.Groups[4].Value;
            if (!DateTime.TryParse($"{year}/{month}/{day} {time}:59", out var latest))
                latest = DateTime.Now;
            if (latest > DateTime.Now)
                latest = DateTime.Now;
            this._latest = latest;
            this._getActive = false;
            this.RefrashLatest();
            return;
        }

        public void RefrashLatest()
        {
            if (!this._init || this._getActive)
                return;
            var check = this._latest;
            while (check < DateTime.Now)
            {
                this._latest = check;
                check += TimeSpan.FromMinutes(PluginConfig.Instance.refreshInterval);
            }
        }
    }
}

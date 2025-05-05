using System;
using System.Net.Http;
using System.Reflection;
using System.Threading.Tasks;

namespace JBSLViewer.Util
{
    public static class HttpUtility
    {
        public static readonly HttpClient httpClient = new HttpClient();
        public static bool Init = false;
        public static async Task<string> GetHttpContentAsync(string url)
        {
            var assenblyName = Assembly.GetExecutingAssembly().GetName();
            var version = Assembly.GetExecutingAssembly().GetName().Version.ToString();
            if (!Init)
            {
                Init = true;
                httpClient.DefaultRequestHeaders.TryAddWithoutValidation("User-Agent", $"{assenblyName}/{version}");
            }
            try
            {
                return await httpClient.GetStringAsync(url);
            }
            catch (HttpRequestException e)
            {
                Plugin.Log.Error($"{url} Http Error : {e.Message}");
                return null;
            }
            catch (TaskCanceledException e)
            {
                Plugin.Log.Error($"{url} Http Cancel : {e.Message}");
                return null;
            }
            catch (Exception e)
            {
                Plugin.Log.Error($"{url} Http other Error : {e.Message}");
                return null;
            }
        }
    }
}

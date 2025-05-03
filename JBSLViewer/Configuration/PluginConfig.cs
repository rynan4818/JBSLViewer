using System.Runtime.CompilerServices;
using IPA.Config.Stores;

[assembly: InternalsVisibleTo(GeneratedStore.AssemblyVisibilityTarget)]
namespace JBSLViewer.Configuration
{
    internal class PluginConfig
    {
        public static PluginConfig Instance { get; set; }
        public virtual int refreshInterval { get; set; } = 10; // 更新間隔（分）
        public virtual int selectLeagueID { get; set; } = -1; // 選択中のリーグID
        public virtual string leaderboardApiUrl { get; set; } = "https://jbsl-web.herokuapp.com/leaderboard/api/";
        public virtual string activeLeagueApiUrl { get; set; } = "https://jbsl-web.herokuapp.com/api/active_league";
        public virtual string headlinesUrl { get; set; } = "https://jbsl-web.herokuapp.com/headlines/1";
        public virtual string headlineLatest { get; set; } = @"（(\d{1,4})年(\d{1,2})月(\d{1,2})日(\d{1,2}:\d{1,2})）"; // ヘッドラインの日付正規表現

        /// <summary>
        /// これは、BSIPAが設定ファイルを読み込むたびに（ファイルの変更が検出されたときを含めて）呼び出されます
        /// </summary>
        public virtual void OnReload()
        {
            // 設定ファイルを読み込んだ後の処理を行う
        }

        /// <summary>
        /// これを呼び出すと、BSIPAに設定ファイルの更新を強制します。 これは、ファイルが変更されたことをBSIPAが検出した場合にも呼び出されます。
        /// </summary>
        public virtual void Changed()
        {
            // 設定が変更されたときに何かをします
        }

        /// <summary>
        /// これを呼び出して、BSIPAに値を<paramref name ="other"/>からこの構成にコピーさせます。
        /// </summary>
        public virtual void CopyFrom(PluginConfig other)
        {
            // このインスタンスのメンバーは他から移入されました
        }
    }
}

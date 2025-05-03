using System;
using HMUI;
using Zenject;
using LeaderboardCore.Managers;
using LeaderboardCore.Models;
using JBSLViewer.Views;

namespace JBSLViewer.Registerers
{
    public class LeaderboardRegisterer : CustomLeaderboard, IInitializable, IDisposable
    {
        private readonly CustomLeaderboardManager _customLeaderboardManager;
        private readonly LeaderboardPanelViewController _leaderboardPanelViewController;
        private readonly LeaderboardMainViewController _leaderboardMainViewController;
        private bool disposedValue;

        public LeaderboardRegisterer(
            CustomLeaderboardManager customLeaderboardManager,
            LeaderboardPanelViewController leaderboardPanelViewController,
            LeaderboardMainViewController leaderboardMainViewController)
        {
            this._customLeaderboardManager = customLeaderboardManager;
            this._leaderboardPanelViewController = leaderboardPanelViewController;
            this._leaderboardMainViewController = leaderboardMainViewController;
        }

        protected override ViewController panelViewController => this._leaderboardPanelViewController;

        protected override ViewController leaderboardViewController => this._leaderboardMainViewController;

        public void Initialize()
        {
            this._customLeaderboardManager.Register(this);
        }

        protected virtual void Dispose(bool disposing)
        {
            if (!disposedValue)
            {
                if (disposing)
                {
                    this._customLeaderboardManager.Unregister(this);
                }

                // TODO: アンマネージド リソース (アンマネージド オブジェクト) を解放し、ファイナライザーをオーバーライドします
                // TODO: 大きなフィールドを null に設定します
                disposedValue = true;
            }
        }

        // // TODO: 'Dispose(bool disposing)' にアンマネージド リソースを解放するコードが含まれる場合にのみ、ファイナライザーをオーバーライドします
        // ~LeaderboardRegisterer()
        // {
        //     // このコードを変更しないでください。クリーンアップ コードを 'Dispose(bool disposing)' メソッドに記述します
        //     Dispose(disposing: false);
        // }

        public void Dispose()
        {
            // このコードを変更しないでください。クリーンアップ コードを 'Dispose(bool disposing)' メソッドに記述します
            Dispose(disposing: true);
            GC.SuppressFinalize(this);
        }
    }
}

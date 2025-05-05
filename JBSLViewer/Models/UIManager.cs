using System;
using System.Text.RegularExpressions;
using Zenject;
using JBSLViewer.Views;

namespace JBSLViewer.Models
{
    internal class UIManager : IInitializable, IDisposable
    {
        private bool disposedValue;
        private readonly StandardLevelDetailViewController _standardLevelDetail;
        private readonly LeaderboardInfo _leaderboardInfo;
        private readonly Leaderboard _leaderboard;
        private readonly LeaderboardPanelViewController _leaderboardPanelViewController;

        public UIManager(StandardLevelDetailViewController standardLevelDetail, LeaderboardInfo leaderboardInfo, Leaderboard leaderboard, LeaderboardPanelViewController leaderboardPanelViewController)
        {
            this._standardLevelDetail = standardLevelDetail;
            this._leaderboardInfo = leaderboardInfo;
            this._leaderboard = leaderboard;
            this._leaderboardPanelViewController = leaderboardPanelViewController;
        }

        public void Initialize()
        {
            this._standardLevelDetail.didChangeDifficultyBeatmapEvent += StandardLevelDetail_didChangeDifficultyBeatmapEvent;
            this._standardLevelDetail.didChangeContentEvent += StandardLevelDetail_didChangeContentEvent;
        }
        public void StandardLevelDetail_didChangeDifficultyBeatmapEvent(StandardLevelDetailViewController arg1, IDifficultyBeatmap arg2)
        {
            if (arg1 != null && arg2 != null)
                BeatmapInfoUpdated(arg2);
        }
        public void StandardLevelDetail_didChangeContentEvent(StandardLevelDetailViewController arg1, StandardLevelDetailViewController.ContentType arg2)
        {
            if (arg1 != null && arg1.selectedDifficultyBeatmap != null)
                BeatmapInfoUpdated(arg1.selectedDifficultyBeatmap);
        }
        public void BeatmapInfoUpdated(IDifficultyBeatmap beatmap)
        {
            if (LeaderboardPanelViewController.AllResetSemaphore.CurrentCount == 0 || LeaderboardPanelViewController.SetLeaderboardSemaphore.CurrentCount == 0)
                return;
            var levelId = beatmap?.level?.levelID;
            if (levelId == null)
                return;
            // 13は "custom_level_"、40はSHA-1ハッシュの長さを表すマジックナンバー
            var hash = Regex.IsMatch(levelId, "^custom_level_[0-9A-F]{40}", RegexOptions.IgnoreCase) && !levelId.EndsWith(" WIP") ? levelId.Substring(13, 40) : null;
            if (hash == null)
                return;
            if (!int.TryParse(this._leaderboardPanelViewController.JBSLLeagueValue, out var leagueID))
                return;
            var maps = this._leaderboard.GetMap(leagueID);
            for (var i = 0; i < maps.Count; i++)
            {
                if (maps[i].lid == null)
                    continue;
                string leaderboardHash;
                if (maps[i].hash != null && Regex.IsMatch(maps[i].hash, "[0-9A-F]{40}", RegexOptions.IgnoreCase))
                    leaderboardHash = maps[i].hash;
                else
                    leaderboardHash = this._leaderboardInfo.GetSongHash(maps[i].lid);
                if (leaderboardHash == null)
                    continue;
                if (leaderboardHash.Equals(hash, StringComparison.OrdinalIgnoreCase))
                {
                    this._leaderboardPanelViewController.SetLeaderboard((i + 1).ToString());
                    break;
                }
            }
        }

        protected virtual void Dispose(bool disposing)
        {
            if (!disposedValue)
            {
                if (disposing)
                {
                    // TODO: マネージド状態を破棄します (マネージド オブジェクト)
                    this._standardLevelDetail.didChangeDifficultyBeatmapEvent -= StandardLevelDetail_didChangeDifficultyBeatmapEvent;
                    this._standardLevelDetail.didChangeContentEvent -= StandardLevelDetail_didChangeContentEvent;
                }

                // TODO: アンマネージド リソース (アンマネージド オブジェクト) を解放し、ファイナライザーをオーバーライドします
                // TODO: 大きなフィールドを null に設定します
                disposedValue = true;
            }
        }

        // // TODO: 'Dispose(bool disposing)' にアンマネージド リソースを解放するコードが含まれる場合にのみ、ファイナライザーをオーバーライドします
        // ~UIManager()
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

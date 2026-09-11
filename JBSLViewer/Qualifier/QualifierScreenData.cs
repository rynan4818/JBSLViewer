using System;
using System.Linq;
using JBSLViewer.Models.JBSL;
using JBSLViewer.Qualifier.Core;
using JBSLViewer.Qualifier.Core.Contracts;

namespace JBSLViewer.Qualifier
{
    public static class QualifierScreenData
    {
        public static bool Matches(MapKey key, string hash, string characteristic, string difficulty)
        {
            try { return key != null && key.Equals(MapKey.Create(hash, characteristic, difficulty)); }
            catch (Exception) { return false; }
        }

        public static Map FindRankingMap(LeaderboardJson board, MapKey key)
        {
            var index = FindRankingIndex(board, key);
            return index < 0 ? null : board.maps[index];
        }

        public static int FindRankingIndex(LeaderboardJson board, MapKey key)
        {
            var found = -1;
            if (board?.maps == null || key == null) return found;
            for (var index = 0; index < board.maps.Count; index++)
            {
                var map = board.maps[index];
                if (map == null || !Matches(key, map.hash, map.characteristic, map.difficulty)) continue;
                if (found >= 0) return -1; // Never choose an ambiguous difficulty.
                found = index;
            }
            return found;
        }

        public sealed class LeagueEntryNotice
        {
            public string Title { get; }
            public string Message { get; }
            public LeagueEntryNotice(string title, string message) { Title = title; Message = message; }
        }

        public static LeagueEntryNotice LeagueEntryProblem(LeaderboardContract board, int leagueId, bool fresh,
            string requestedSid, string currentSid)
        {
            if (!fresh || board == null || board.LeagueId != leagueId)
                return new LeagueEntryNotice("参加状況を確認できませんでした", "リーグ情報を取得・確認できませんでした。RELOADで再読み込みしてください。");
            if (board.Qualifier?.Enabled != true || board.Qualifier.SubmissionMethod != "jbsl_qualifier_v1")
                return new LeagueEntryNotice("チャレンジ非対応のリーグ", "このリーグはJBSLチャレンジに対応していません。");
            if (string.IsNullOrWhiteSpace(currentSid) || !string.Equals(requestedSid, currentSid, StringComparison.Ordinal))
                return new LeagueEntryNotice("参加状況を確認できませんでした", "プレイヤー情報を確認できないか、アカウントが変更されました。もう一度リーグを選択してください。");
            if (board.Participants == null || board.Participants.Any(p => string.IsNullOrWhiteSpace(p?.Sid) || p.Sid.Trim() != p.Sid)
                || board.Participants.GroupBy(p => p.Sid, StringComparer.Ordinal).Any(g => g.Count() != 1))
                return new LeagueEntryNotice("参加状況を確認できませんでした", "参加者情報を確認できませんでした。RELOADで再読み込みしてください。");
            if (!board.Participants.Any(p => string.Equals(p.Sid, currentSid, StringComparison.Ordinal)))
                return new LeagueEntryNotice("未参加のリーグ", "このリーグには参加していません。");
            if (board.Maps == null || board.Maps.Count == 0)
                return new LeagueEntryNotice("対象曲がありません", "このリーグにはチャレンジ対象曲が登録されていません。");
            return null;
        }

        public static string LeagueProblem(LeaderboardContract board)
        {
            if (board == null) return "Could not read this league's challenge data. Reload to try again.";
            if (board.Qualifier?.Enabled != true || board.Qualifier.SubmissionMethod != "jbsl_qualifier_v1")
                return "This league does not support JBSL challenges.";
            if (board.Maps == null || board.Maps.Count == 0) return "This league has no challenge maps.";
            return null;
        }

        public static string SelectionProblem(SelectionSnapshot selection, DateTimeOffset now)
        {
            var board = selection?.Leaderboard;
            var problem = LeagueProblem(board);
            if (problem != null) return problem;
            if (!selection.LeaderboardFresh) return "League data is unavailable or out of date. Reload to try again.";
            if (string.IsNullOrEmpty(selection.CurrentSid)) return "Waiting for your platform account...";
            if (board.Participants?.Count(p => p.Sid == selection.CurrentSid) != 1) return "You are not registered for this league.";
            if (!board.IsLive || !board.IsOpen) return "This league is not accepting challenges.";
            if (board.Qualifier.StartsAt.HasValue && now < board.Qualifier.StartsAt) return "This challenge has not opened yet.";
            if (selection.Map == null) return "Select a challenge map.";
            if (!selection.LocalSongDurationSeconds.HasValue) return "The selected map is not ready. Reload the map.";
            var end = board.Qualifier.EndsAt ?? board.End;
            if (now > end.AddSeconds(-selection.LocalSongDurationSeconds.Value)) return "There is not enough time to finish this song before the deadline.";
            if (board.Maps.Count(m => m.Key.Equals(selection.Map)) != 1) return "This difficulty is not a challenge map.";
            if (!selection.IsSolo) return "The selected map is not available for a Solo challenge.";
            return null;
        }
    }
}

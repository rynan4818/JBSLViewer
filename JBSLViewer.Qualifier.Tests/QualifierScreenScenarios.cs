using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using JBSLViewer.Models.JBSL;
using JBSLViewer.Qualifier.Core;
using JBSLViewer.Qualifier.Core.Contracts;
using Newtonsoft.Json;

namespace JBSLViewer.Qualifier.Tests
{
    internal static class QualifierScreenScenarios
    {
        internal static async Task Run()
        {
            const string hash = "0123456789ABCDEF0123456789ABCDEF01234567";
            var expert = MapKey.Create(hash, "Standard", "Expert");
            var plus = MapKey.Create(hash, "Standard", "ExpertPlus");
            var lawless = MapKey.Create(hash, "Lawless", "ExpertPlus");
            var board = JsonConvert.DeserializeObject<LeaderboardJson>(@"{'maps':[
                {'hash':'0123456789abcdef0123456789abcdef01234567','characteristic':'Standard','difficulty':'Expert','title':'Expert'},
                {'hash':'0123456789ABCDEF0123456789ABCDEF01234567','characteristic':'Standard','difficulty':'ExpertPlus','title':'ExpertPlus'},
                {'hash':'0123456789ABCDEF0123456789ABCDEF01234567','characteristic':'Lawless','difficulty':'ExpertPlus','title':'Lawless'}]}");
            Program.Check(QualifierScreenData.FindRankingMap(board, expert)?.title == "Expert", "room ranking matches exact difficulty");
            Program.Check(QualifierScreenData.FindRankingMap(board, plus)?.title == "ExpertPlus", "room ranking does not use first matching hash");
            Program.Check(QualifierScreenData.FindRankingMap(board, lawless)?.title == "Lawless", "room ranking matches exact characteristic");
            Program.Check(QualifierScreenData.FindRankingIndex(board, plus) == 1, "shared leaderboard resolves the selected map index");
            board.maps.Reverse();
            Program.Check(QualifierScreenData.FindRankingIndex(board, expert) == 2 && QualifierScreenData.FindRankingIndex(board, lawless) == 0,
                "shared leaderboard follows the MapKey when a refreshed board reorders maps");
            Program.Check(QualifierScreenData.FindRankingMap(board, MapKey.Create(hash, "Standard", "Easy")) == null, "room ranking missing difficulty has no fallback");
            board.maps.Add(board.maps[1]);
            Program.Check(QualifierScreenData.FindRankingMap(board, plus) == null, "room ranking rejects ambiguous map entries");
            Program.Check(QualifierScreenData.FindRankingIndex(board, plus) == -1 && QualifierScreenData.FindRankingIndex(null, expert) == -1,
                "missing and ambiguous rankings cannot fall back to the total or another map");
            Program.Check(!QualifierScreenData.Matches(plus, hash, null, null), "room ranking rejects legacy hash-only identity");
            Program.Check(QualifierScreenData.Matches(plus, hash.ToLowerInvariant(), "Standard", "Expert+"), "room ranking normalizes valid key aliases");

            var state = new QualifierRoomState();
            Program.Check(!state.BeginLaunch(false), "room cannot launch before opening");
            var loadGeneration = state.Open(3023, plus);
            plus.Hash = new string('F', 40);
            Program.Check(state.Map.Hash == hash, "room owns a copy of navigation map identity");
            var delayed = new TaskCompletionSource<bool>();
            var staleApplied = false;
            var load = ApplyWhenReady();
            state.Select(3023, lawless);
            delayed.SetResult(true);
            await load;
            Program.Check(!staleApplied, "old song completion cannot replace a newer selection");
            Program.Check(state.BeginLaunch(false) && !state.BeginLaunch(false), "room starts at most one launch");
            var launchId = state.LaunchId;
            Program.Check(state.IsOpen && state.IsCurrentLaunch(launchId) && state.Map.Equals(lawless), "room retains its hierarchy and identity throughout direct play");
            state.GameplayFinished();
            Program.Check(!state.ReturnReady, "menu activation before gameplay does not trigger a return");
            state.GameplayStarted(); state.GameplayFinished();
            Program.Check(state.ReturnReady, "finished gameplay enables room restoration");
            Program.Check(state.CompleteLaunch(launchId, true) && state.ShowingResults && !state.BeginLaunch(true), "results retain the selection and block another launch");
            Program.Check(!state.CompleteLaunch(launchId, false) && state.ShowingResults, "duplicate completion cannot close displayed results");
            state.Resume();
            Program.Check(state.IsOpen && !state.LaunchPending && !state.GameplaySeen && !state.ReturnReady && !state.ShowingResults
                && state.Map.Equals(lawless), "continuing from results restores the same detail and clears play flags");
            Program.Check(!state.IsCurrent(loadGeneration), "old loading completion remains invalid after results");
            Program.Check(state.BeginLaunch(true) && state.Practice, "normal practice has a distinct navigation state");
            Program.Check(state.LaunchId != launchId && !state.CompleteLaunch(launchId, false), "old result cannot complete a newer launch");
            state.LaunchFailed("load failed");
            Program.Check(state.ReturnReady && state.Notice == "load failed", "explicit launch failure restores room with an explanation");
            state.Close();
            Program.Check(!state.IsOpen && !state.LaunchPending && state.Map == null && state.LeagueId == 0, "closing clears return and launch state");
            Program.Check(!state.CompleteLaunch(state.LaunchId, true) && !state.IsOpen, "a late result cannot reopen a closed room");
            state.GameplayStarted(); state.GameplayFinished();
            Program.Check(!state.ReturnReady, "ordinary gameplay after leaving cannot reopen the room");

            var now = new TestClock().UtcNow;
            var selection = Rig.Selection(now, "player");
            CheckLeagueEntry(selection.Leaderboard);
            Program.Check(QualifierScreenData.SelectionProblem(selection, now) == null, "eligible room selection has no local blocker");
            selection.CurrentSid = "outsider";
            Program.Check(QualifierScreenData.SelectionProblem(selection, now).Contains("not registered"), "room explains nonparticipant restriction");
            selection.CurrentSid = "player"; selection.LeaderboardFresh = false;
            Program.Check(QualifierScreenData.SelectionProblem(selection, now).Contains("out of date"), "room explains stale league data");
            selection.LeaderboardFresh = true; selection.Leaderboard.End = now.AddSeconds(30);
            Program.Check(QualifierScreenData.SelectionProblem(selection, now).Contains("not enough time"), "room explains deadline relative to song duration");
            selection.Leaderboard.End = now.AddHours(1); selection.IsSolo = false;
            Program.Check(QualifierScreenData.SelectionProblem(selection, now).Contains("Solo"), "room explains unsupported selection state");
            selection.Leaderboard.Qualifier.Enabled = false;
            Program.Check(QualifierScreenData.LeagueProblem(selection.Leaderboard).Contains("does not support"), "room explains unsupported league");

            using (var rig = new Rig())
            {
                rig.Api.Status = (session, gate) =>
                {
                    var status = rig.Api.StatusSuccess(gate);
                    status.Eligible = false; status.ReasonCode = "not_participant";
                    return Task.FromResult(status);
                };
                await rig.Coordinator.RefreshAsync();
                Program.Check(!rig.Coordinator.ViewState.CanChallenge && rig.Coordinator.ViewState.Message == "not_participant",
                    "room retains the server's refusal reason while keeping Challenge disabled");
            }

            async Task ApplyWhenReady() { await delayed.Task; if (state.IsCurrent(loadGeneration)) staleApplied = true; }
        }

        private static void CheckLeagueEntry(LeaderboardContract source)
        {
            var board = StrictJson.Clone(source);
            var id = board.LeagueId;
            QualifierScreenData.LeagueEntryNotice Entry(string sid = "player", bool fresh = true, string requestedSid = "player")
                => QualifierScreenData.LeagueEntryProblem(board, id, fresh, requestedSid, sid);
            Program.Check(Entry() == null, "registered participants may enter without any score or total ranking entry");
            var notice = Entry("outsider", requestedSid: "outsider");
            Program.Check(notice?.Title == "未参加のリーグ" && notice.Message == "このリーグには参加していません。",
                "league entry reports nonparticipation immediately with the requested dialog text");
            Program.Check(Entry(null)?.Title == "参加状況を確認できませんでした", "missing platform identity never means nonparticipant");
            Program.Check(Entry("outsider")?.Title == "参加状況を確認できませんでした", "an account change during loading cannot produce a stale nonparticipant dialog");
            Program.Check(Entry("outsider", false, "outsider")?.Title == "参加状況を確認できませんでした",
                "failed refresh and stale cached participants never imply nonparticipation");
            Program.Check(QualifierScreenData.LeagueEntryProblem(null, id, true, "player", "player")?.Title == "参加状況を確認できませんでした",
                "missing or invalid strict contract reports unavailable membership");
            Program.Check(QualifierScreenData.LeagueEntryProblem(board, id + 1, true, "player", "player")?.Title == "参加状況を確認できませんでした",
                "membership from a different league cannot authorize entry");
            board.Participants = null;
            Program.Check(Entry()?.Title == "参加状況を確認できませんでした", "missing participants are not interpreted as an empty membership list");
            board.Participants = new List<Participant> { null };
            Program.Check(Entry()?.Title == "参加状況を確認できませんでした", "null participant entries are rejected without throwing");
            board.Participants = new List<Participant> { new Participant { Sid = " player " } };
            Program.Check(Entry()?.Title == "参加状況を確認できませんでした", "invalid participant IDs are not used for membership");
            board.Participants = new List<Participant> { new Participant { Sid = "player" }, new Participant { Sid = "player" } };
            Program.Check(Entry()?.Title == "参加状況を確認できませんでした", "duplicate participants make entry status unavailable");
            board.Participants.Clear();
            Program.Check(Entry()?.Title == "未参加のリーグ", "validated empty participant lists show nonparticipation");
            board.Participants.Add(new Participant { Sid = "player" });
            board.Qualifier.Enabled = false;
            Program.Check(Entry()?.Title == "チャレンジ非対応のリーグ", "unsupported leagues have a visible reason dialog");
            board.Qualifier.Enabled = true; board.Maps.Clear();
            Program.Check(Entry()?.Title == "対象曲がありません", "participants in a league without maps see a separate explanation");
        }
    }
}

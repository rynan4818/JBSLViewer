using BS_Utils.Gameplay;
using JBSLViewer.Configuration;
using JBSLViewer.Models.BeatLeader;
using JBSLViewer.Models.JBSL;
using JBSLViewer.Models.ScoreSaber;
using JBSLViewer.Util;
using Newtonsoft.Json;
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Security.Policy;
using System.Threading;
using System.Threading.Tasks;

namespace JBSLViewer.Models
{
    public class VirtualLeagueService : IDisposable
    {
        private readonly ActiveLeague _activeLeague;
        private readonly Leaderboard _leaderboard;
        private readonly LeaderboardInfo _leaderboardInfo;
        private readonly SemaphoreSlim _updateSemaphore = new SemaphoreSlim(1, 1);
        private readonly Dictionary<int, VirtualLeagueState> _leagueStates = new Dictionary<int, VirtualLeagueState>();
        private bool _disposedValue;
        private Task<string> _selfSidTask;
        private string _selfSid;
        private string _selfName;
        private static readonly TimeSpan ScoreSaberRecentFreshnessWindow = TimeSpan.FromMinutes(10);

        public event Action<int> VirtualLeaderboardUpdated;
        public event Action<int> VirtualAvailabilityChanged;
        public event Action<int, int, int, bool> VirtualParticipationProgressChanged;

        public VirtualLeagueService(ActiveLeague activeLeague, Leaderboard leaderboard, LeaderboardInfo leaderboardInfo)
        {
            this._activeLeague = activeLeague;
            this._leaderboard = leaderboard;
            this._leaderboardInfo = leaderboardInfo;
        }

        public bool TryRefreshCurrentUser()
        {
            if (this._selfSidTask == null)
                this._selfSidTask = FetchCurrentUserSidAsync();
            if (!this._selfSidTask.IsCompleted)
                return false;

            string sid;
            try
            {
                sid = this._selfSidTask.GetAwaiter().GetResult();
            }
            catch (Exception ex)
            {
                Plugin.Log?.Error(ex.ToString());
                this._selfSidTask = null;
                return false;
            }

            if (string.IsNullOrEmpty(sid))
            {
                this._selfSidTask = null;
                return false;
            }

            return this.ApplyCurrentUserSid(sid);
        }

        public bool IsVirtualParticipationAvailable(int leagueId)
        {
            if (!this.TryGetLeagueContext(leagueId, out var league, out var sourceLeaderboard))
                return false;
            if (string.IsNullOrEmpty(this._selfSid))
                return false;
            if (!league.playlist_id.HasValue)
                return false;
            return !this.IsSelfInTotal(sourceLeaderboard);
        }

        public bool IsVirtualParticipationEnabled(int leagueId)
        {
            if (!this._leagueStates.TryGetValue(leagueId, out var state))
                return false;
            if (!state.IsEnabled || !state.Initialized)
                return false;
            return this.IsVirtualParticipationAvailable(leagueId);
        }

        public bool TryGetVirtualParticipationProgress(int leagueId, out int completedMaps, out int totalMaps, out bool isActive)
        {
            if (this._leagueStates.TryGetValue(leagueId, out var state))
            {
                completedMaps = state.ProgressCompleted;
                totalMaps = state.ProgressTotal;
                isActive = state.ProgressActive;
                return true;
            }

            completedMaps = 0;
            totalMaps = 0;
            isActive = false;
            return false;
        }

        public bool SyncLeagueParticipationState(int leagueId)
        {
            if (!this.TryGetLeagueContext(leagueId, out _, out var sourceLeaderboard))
                return false;
            if (!this.IsSelfInTotal(sourceLeaderboard))
                return false;
            if (!this._leagueStates.TryGetValue(leagueId, out var state) || !state.IsEnabled)
                return false;

            state.IsEnabled = false;
            state.Dirty = true;
            this.RaiseAvailabilityChanged(leagueId);
            this.RaiseVirtualLeaderboardUpdated(leagueId);
            return true;
        }

        public LeaderboardJson GetLeaderboardForDisplay(int leagueId)
        {
            var sourceLeaderboard = this._leaderboard.GetLeaderboardData(leagueId);
            if (sourceLeaderboard == null)
                return null;
            if (!this._leagueStates.TryGetValue(leagueId, out var state) || !state.Initialized || !state.IsEnabled)
                return sourceLeaderboard;
            if (this.IsSelfInTotal(sourceLeaderboard))
                return sourceLeaderboard;

            return this.BuildVirtualLeaderboardIfNeeded(leagueId, state, sourceLeaderboard, false) ?? sourceLeaderboard;
        }

        public async Task SetVirtualParticipationEnabledAsync(int leagueId, bool enabled)
        {
            if (!enabled)
            {
                if (this._leagueStates.TryGetValue(leagueId, out var existingState) && existingState.IsEnabled)
                {
                    existingState.IsEnabled = false;
                    this.UpdateProgress(existingState, 0, 0, false);
                    this.RaiseVirtualLeaderboardUpdated(leagueId);
                }

                this.RaiseAvailabilityChanged(leagueId);
                return;
            }

            await this.EnsureCurrentUserSidAsync();
            if (!this.IsVirtualParticipationAvailable(leagueId))
            {
                this.RaiseAvailabilityChanged(leagueId);
                return;
            }

            await this._updateSemaphore.WaitAsync();
            try
            {
                if (!this.TryGetLeagueContext(leagueId, out var league, out var sourceLeaderboard))
                    return;

                var state = this.GetOrCreateState(leagueId);
                state.PlaylistId = league.playlist_id.Value;
                await this.EnsureSelfNameAsync();
                await this.EnsurePlaylistSongsAsync(state);
                await this.EnsureMapCachesAsync(state, sourceLeaderboard.maps);
                state.Initialized = true;
                state.IsEnabled = true;
                state.Dirty = true;
                this.BuildVirtualLeaderboardIfNeeded(leagueId, state, sourceLeaderboard, true);
            }
            finally
            {
                if (this._leagueStates.TryGetValue(leagueId, out var state))
                    this.UpdateProgress(state, state.ProgressCompleted, state.ProgressTotal, false);
                this._updateSemaphore.Release();
            }

            this.RaiseAvailabilityChanged(leagueId);
            this.RaiseVirtualLeaderboardUpdated(leagueId);
        }

        public async Task HandleScoreUploadedAsync()
        {
            if (!this._leagueStates.Values.Any(x => x.Initialized))
                return;

            await this.EnsureCurrentUserSidAsync();
            if (string.IsNullOrEmpty(this._selfSid))
                return;

            var updatedLeagueIds = new List<int>();
            await this._updateSemaphore.WaitAsync();
            try
            {
                var useBeatLeaderFallback = await this.TryApplyRecentScoreSaberScoresAsync(updatedLeagueIds);
                if (useBeatLeaderFallback)
                    await this.TryApplyRecentBeatLeaderScoresAsync(updatedLeagueIds);

                this.RebuildUpdatedVirtualLeaderboards(updatedLeagueIds);
            }
            finally
            {
                this._updateSemaphore.Release();
            }

            this.RaiseVirtualLeaderboardUpdated(updatedLeagueIds);
        }

        private async Task<bool> TryApplyRecentScoreSaberScoresAsync(List<int> updatedLeagueIds)
        {
            var recentUrl = $"{PluginConfig.Instance.scoreSaberPlayerUrlHeader}{this._selfSid}{PluginConfig.Instance.scoreSaberRecentScoresUrlFooter}";
            var resJsonString = await HttpUtility.GetHttpContentAsync(recentUrl);
            if (string.IsNullOrWhiteSpace(resJsonString))
                return true;

            ScoreSaberPlayerRecentScoresJson recentScores;
            try
            {
                recentScores = JsonConvert.DeserializeObject<ScoreSaberPlayerRecentScoresJson>(resJsonString);
            }
            catch (Exception ex)
            {
                Plugin.Log?.Error(ex.ToString());
                return true;
            }

            if (recentScores?.playerScores == null || recentScores.playerScores.Count <= 0)
                return true;
            if (!IsRecentScoreFresh(recentScores.playerScores[0]?.score?.timeSet))
                return true;

            foreach (var recentScore in recentScores.playerScores)
            {
                var lid = recentScore?.leaderboard?.id.ToString();
                if (string.IsNullOrEmpty(lid) || recentScore.score == null)
                    continue;

                this.ApplySelfScoreToInitializedStatesByLid(
                    lid,
                    recentScore.score.modifiedScore,
                    recentScore.score.badCuts + recentScore.score.missedNotes,
                    recentScore.leaderboard?.maxScore,
                    updatedLeagueIds);
            }

            return false;
        }

        private async Task TryApplyRecentBeatLeaderScoresAsync(List<int> updatedLeagueIds)
        {
            var url = $"https://api.beatleader.com/player/{this._selfSid}/scores/compact?sortBy=date&order=desc";
            var resJsonString = await HttpUtility.GetHttpContentAsync(url, true);
            if (string.IsNullOrWhiteSpace(resJsonString))
                return;

            BeatLeaderCompactScoresJson compactScores;
            try
            {
                compactScores = JsonConvert.DeserializeObject<BeatLeaderCompactScoresJson>(resJsonString);
            }
            catch (Exception ex)
            {
                Plugin.Log?.Error(ex.ToString());
                return;
            }

            if (compactScores?.data == null || compactScores.data.Count <= 0)
                return;

            var appliedMapKeys = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var recentScore in compactScores.data)
            {
                if (recentScore?.score == null || recentScore.leaderboard == null)
                    continue;

                var mapKey = CreateBeatLeaderMapKey(
                    recentScore.leaderboard.songHash,
                    recentScore.leaderboard.modeName,
                    recentScore.leaderboard.difficulty);
                if (string.IsNullOrEmpty(mapKey) || !appliedMapKeys.Add(mapKey))
                    continue;

                foreach (var state in this._leagueStates.Values.Where(x => x.Initialized))
                {
                    foreach (var mapState in state.MapStates.Values)
                    {
                        if (!IsBeatLeaderCompactMatch(mapState, recentScore.leaderboard))
                            continue;

                        this.ApplySelfScoreToMapState(
                            state,
                            mapState,
                            recentScore.score.modifiedScore,
                            recentScore.score.badCuts + recentScore.score.missedNotes,
                            null,
                            updatedLeagueIds);
                    }
                }
            }
        }

        private void ApplySelfScoreToInitializedStatesByLid(string lid, int rawScore, int miss, int? maxScore, List<int> updatedLeagueIds)
        {
            foreach (var state in this._leagueStates.Values.Where(x => x.Initialized))
            {
                if (!state.MapStates.TryGetValue(lid, out var mapState))
                    continue;

                this.ApplySelfScoreToMapState(state, mapState, rawScore, miss, maxScore, updatedLeagueIds);
            }
        }

        private void ApplySelfScoreToMapState(VirtualLeagueState state, VirtualMapState mapState, int rawScore, int miss, int? maxScore, List<int> updatedLeagueIds)
        {
            if (state == null || mapState == null)
                return;

            mapState.InitialSelfScoreFetched = true;
            mapState.SelfScore = new VirtualSelfScore
            {
                HasScore = true,
                RawScore = rawScore,
                Miss = Math.Max(0, miss),
            };

            if (maxScore.HasValue && maxScore.Value > 0)
            {
                mapState.ScoreSaberInfoFetched = true;
                mapState.ScoreSaberMaxScore = maxScore.Value;
                this.LogMaxScoreDifference(mapState);
            }

            state.Dirty = true;
            if (!updatedLeagueIds.Contains(state.LeagueId))
                updatedLeagueIds.Add(state.LeagueId);
        }

        private void RebuildUpdatedVirtualLeaderboards(List<int> updatedLeagueIds)
        {
            foreach (var leagueId in updatedLeagueIds)
            {
                if (!this._leagueStates.TryGetValue(leagueId, out var state))
                    continue;

                var sourceLeaderboard = this._leaderboard.GetLeaderboardData(leagueId);
                if (sourceLeaderboard == null)
                    continue;

                this.BuildVirtualLeaderboardIfNeeded(leagueId, state, sourceLeaderboard, true);
            }
        }

        public void OnAccuracyModeChanged()
        {
            var updatedLeagueIds = new List<int>();
            foreach (var state in this._leagueStates.Values.Where(x => x.Initialized))
            {
                state.Dirty = true;
                if (state.IsEnabled)
                    updatedLeagueIds.Add(state.LeagueId);
            }

            this.RaiseVirtualLeaderboardUpdated(updatedLeagueIds);
        }

        private async Task EnsureSelfNameAsync()
        {
            if (!string.IsNullOrEmpty(this._selfName) || string.IsNullOrEmpty(this._selfSid))
                return;

            var url = $"{PluginConfig.Instance.scoreSaberPlayerUrlHeader}{this._selfSid}/basic";
            var resJsonString = await HttpUtility.GetHttpContentAsync(url);
            if (resJsonString != null)
            {
                var playerInfo = JsonConvert.DeserializeObject<PlayerFullInfoJson>(resJsonString);
                if (!string.IsNullOrWhiteSpace(playerInfo?.name))
                    this._selfName = playerInfo.name;
            }
        }

        private async Task<bool> EnsureCurrentUserSidAsync()
        {
            if (!string.IsNullOrEmpty(this._selfSid))
                return true;

            if (this._selfSidTask == null)
                this._selfSidTask = FetchCurrentUserSidAsync();

            string sid;
            try
            {
                sid = await this._selfSidTask;
            }
            catch (Exception ex)
            {
                Plugin.Log?.Error(ex.ToString());
                this._selfSidTask = null;
                return false;
            }

            if (string.IsNullOrEmpty(sid))
            {
                this._selfSidTask = null;
                return false;
            }

            this.ApplyCurrentUserSid(sid);
            return !string.IsNullOrEmpty(this._selfSid);
        }

        private bool ApplyCurrentUserSid(string sid)
        {
            if (string.IsNullOrEmpty(sid) || string.Equals(this._selfSid, sid, StringComparison.Ordinal))
                return false;

            this._selfSid = sid;
            this._selfName = null;
            foreach (var state in this._leagueStates.Values)
                state.Dirty = true;
            this.RaiseAvailabilityChanged(this._leagueStates.Keys);
            return true;
        }

        private static async Task<string> FetchCurrentUserSidAsync()
        {
            var userInfo = await GetUserInfo.GetUserAsync();
            return userInfo?.platformUserId;
        }

        private async Task EnsurePlaylistSongsAsync(VirtualLeagueState state)
        {
            if (state.PlaylistSongsLoaded || state.PlaylistId <= 0)
                return;

            var url = $"{PluginConfig.Instance.playlistSongsApiUrl}{state.PlaylistId}";
            var resJsonString = await HttpUtility.GetHttpContentAsync(url);
            if (resJsonString == null)
                return;

            var playlistSongs = JsonConvert.DeserializeObject<List<PlaylistSongJson>>(resJsonString);
            if (playlistSongs == null)
                return;

            foreach (var song in playlistSongs)
            {
                if (song == null || string.IsNullOrEmpty(song.lid))
                    continue;
                state.PlaylistSongsByLid[song.lid] = song;
            }

            state.PlaylistSongsLoaded = true;
        }

        private async Task EnsureMapCachesAsync(VirtualLeagueState state, List<Map> maps)
        {
            if (maps == null)
            {
                this.UpdateProgress(state, 0, 0, false);
                return;
            }

            var totalMaps = maps.Count;
            var completedMaps = 0;
            this.UpdateProgress(state, completedMaps, totalMaps, totalMaps > 0);

            foreach (var map in maps)
            {
                try
                {
                    if (map == null || string.IsNullOrEmpty(map.lid))
                        continue;

                    var mapState = state.GetOrCreateMapState(map.lid);
                    mapState.Title = map.title;
                    if (state.PlaylistSongsByLid.TryGetValue(map.lid, out var playlistSong))
                    {
                        mapState.Notes = playlistSong.notes;
                        mapState.Hash = string.IsNullOrEmpty(map.hash) ? playlistSong.hash : map.hash;
                        mapState.Diff = playlistSong.diff;
                        mapState.Characteristic = playlistSong.@char;
                        mapState.WebMaxScore = BuildWebMaxScore(playlistSong.notes);
                    }

                    if (!mapState.ScoreSaberInfoFetched)
                        await this.EnsureScoreSaberInfoAsync(mapState);
                    if (!mapState.InitialSelfScoreFetched)
                        await this.EnsureInitialSelfScoreAsync(mapState);
                }
                finally
                {
                    completedMaps++;
                    this.UpdateProgress(state, completedMaps, totalMaps, true);
                }
            }

            this.UpdateProgress(state, completedMaps, totalMaps, false);
        }

        private async Task EnsureScoreSaberInfoAsync(VirtualMapState mapState)
        {
            if (mapState.ScoreSaberInfoFetched || string.IsNullOrEmpty(mapState.Lid))
                return;

            LeaderboardInfoJson leaderboardInfo = null;
            if (!this._leaderboardInfo.LeaderboardInfos.TryGetValue(mapState.Lid, out leaderboardInfo))
                leaderboardInfo = await this._leaderboardInfo.GetLeaderboardInfoAsync(mapState.Lid);

            mapState.ScoreSaberInfoFetched = true;
            if (leaderboardInfo == null)
                return;

            if (!string.IsNullOrWhiteSpace(leaderboardInfo.songHash) && string.IsNullOrWhiteSpace(mapState.Hash))
                mapState.Hash = leaderboardInfo.songHash;
            mapState.ScoreSaberMaxScore = leaderboardInfo.maxScore > 0 ? leaderboardInfo.maxScore : (int?)null;
            ApplyDifficultyInfo(mapState, leaderboardInfo);
            this.LogMaxScoreDifference(mapState);
        }

        private async Task EnsureInitialSelfScoreAsync(VirtualMapState mapState)
        {
            if (mapState.InitialSelfScoreFetched || string.IsNullOrEmpty(mapState.Lid) || string.IsNullOrEmpty(this._selfSid))
                return;

            await this.EnsureSelfNameAsync();
            if (string.IsNullOrWhiteSpace(this._selfName))
            {
                await this.FinalizeInitialSelfScoreWithBeatLeaderFallbackAsync(mapState);
                return;
            }

            var searchName = this._selfName;
            var encodedSearchName = Uri.EscapeDataString(searchName);
            var page = 1;
            while (true)
            {
                var url = $"{PluginConfig.Instance.leaderboardInfoUrlHeader}{mapState.Lid}/scores?search={encodedSearchName}&page={page}";
                var resJsonString = await HttpUtility.GetHttpContentAsync(url, true);
                if (resJsonString == null)
                {
                    await this.FinalizeInitialSelfScoreWithBeatLeaderFallbackAsync(mapState);
                    return;
                }

                var scorePage = JsonConvert.DeserializeObject<ScoreSaberLeaderboardScoresPageJson>(resJsonString);
                if (scorePage == null || !string.IsNullOrEmpty(scorePage.errorMessage) || scorePage.scores == null)
                {
                    await this.FinalizeInitialSelfScoreWithBeatLeaderFallbackAsync(mapState);
                    return;
                }
                if (scorePage.scores.Count <= 0)
                {
                    mapState.InitialSelfScoreFetched = true;
                    return;
                }

                var ownScore = scorePage.scores.FirstOrDefault(x => string.Equals(x?.leaderboardPlayerInfo?.name, searchName, StringComparison.Ordinal));
                if (ownScore != null)
                {
                    mapState.SelfScore = new VirtualSelfScore
                    {
                        HasScore = true,
                        RawScore = ownScore.modifiedScore,
                        Miss = ownScore.badCuts + ownScore.missedNotes,
                    };
                    mapState.InitialSelfScoreFetched = true;
                    return;
                }

                if (scorePage.metadata == null || scorePage.metadata.itemsPerPage <= 0 || scorePage.metadata.total <= page * scorePage.metadata.itemsPerPage)
                {
                    mapState.InitialSelfScoreFetched = true;
                    return;
                }
                page++;
            }
        }

        private async Task FinalizeInitialSelfScoreWithBeatLeaderFallbackAsync(VirtualMapState mapState)
        {
            await this.TryFetchBeatLeaderSelfScoreAsync(mapState);
            mapState.InitialSelfScoreFetched = true;
        }

        private async Task<bool> TryFetchBeatLeaderSelfScoreAsync(VirtualMapState mapState)
        {
            if (mapState == null ||
                string.IsNullOrEmpty(this._selfSid) ||
                string.IsNullOrWhiteSpace(mapState.Hash) ||
                string.IsNullOrWhiteSpace(mapState.Diff) ||
                string.IsNullOrWhiteSpace(mapState.Characteristic))
                return false;

            var url = $"https://api.beatleader.xyz/score/{this._selfSid}/{mapState.Hash}/{mapState.Diff}/{mapState.Characteristic}";
            var resJsonString = await HttpUtility.GetHttpContentAsync(url, true);
            if (string.IsNullOrWhiteSpace(resJsonString))
                return false;

            var beatLeaderScore = JsonConvert.DeserializeObject<BeatLeaderScoreJson>(resJsonString);
            if (beatLeaderScore == null)
                return false;

            mapState.SelfScore = new VirtualSelfScore
            {
                HasScore = true,
                RawScore = beatLeaderScore.modifiedScore,
                Miss = Math.Max(0, beatLeaderScore.badCuts + beatLeaderScore.missedNotes),
            };
            return true;
        }

        private static void ApplyDifficultyInfo(VirtualMapState mapState, LeaderboardInfoJson leaderboardInfo)
        {
            if (mapState == null || leaderboardInfo?.difficulty == null)
                return;

            if (TryParseDifficultyRaw(leaderboardInfo.difficulty.difficultyRaw, out var diff, out var characteristic))
            {
                mapState.Diff = diff;
                mapState.Characteristic = characteristic;
                return;
            }

            var mappedCharacteristic = MapGameModeToCharacteristic(leaderboardInfo.difficulty.gameMode);
            if (!string.IsNullOrWhiteSpace(mappedCharacteristic))
                mapState.Characteristic = mappedCharacteristic;
        }

        private static bool TryParseDifficultyRaw(string difficultyRaw, out string diff, out string characteristic)
        {
            diff = null;
            characteristic = null;
            if (string.IsNullOrWhiteSpace(difficultyRaw))
                return false;

            var parts = difficultyRaw.Split(new[] { '_' }, StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length < 2)
                return false;

            diff = NormalizeDifficultyName(parts[0]);
            characteristic = MapGameModeToCharacteristic(parts[1]);
            return !string.IsNullOrWhiteSpace(diff) && !string.IsNullOrWhiteSpace(characteristic);
        }

        private static string NormalizeDifficultyName(string difficultyName)
        {
            switch (difficultyName)
            {
                case "Easy":
                case "Normal":
                case "Hard":
                case "Expert":
                case "ExpertPlus":
                    return difficultyName;
                default:
                    return null;
            }
        }

        private static string MapGameModeToCharacteristic(string gameMode)
        {
            switch (gameMode)
            {
                case "SoloStandard":
                case "Standard":
                    return "Standard";
                case "SoloLawless":
                case "Lawless":
                    return "Lawless";
                case "SoloOneSaber":
                case "OneSaber":
                    return "OneSaber";
                case "Solo90Degree":
                case "90Degree":
                    return "90Degree";
                case "Solo360Degree":
                case "360Degree":
                    return "360Degree";
                case "SoloNoArrows":
                case "NoArrows":
                    return "NoArrows";
                default:
                    return null;
            }
        }

        private static bool IsRecentScoreFresh(string timeSet)
        {
            if (string.IsNullOrWhiteSpace(timeSet))
                return false;
            if (!DateTimeOffset.TryParse(timeSet, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal, out var parsedTime))
                return false;

            return DateTimeOffset.UtcNow - parsedTime <= ScoreSaberRecentFreshnessWindow;
        }

        private static bool IsBeatLeaderCompactMatch(VirtualMapState mapState, BeatLeaderCompactLeaderboardJson leaderboard)
        {
            if (mapState == null ||
                leaderboard == null ||
                string.IsNullOrWhiteSpace(mapState.Hash) ||
                string.IsNullOrWhiteSpace(mapState.Characteristic) ||
                string.IsNullOrWhiteSpace(mapState.Diff))
                return false;
            if (!TryMapDifficultyToBeatLeaderValue(mapState.Diff, out var difficulty))
                return false;

            return string.Equals(mapState.Hash, leaderboard.songHash, StringComparison.OrdinalIgnoreCase) &&
                   string.Equals(mapState.Characteristic, leaderboard.modeName, StringComparison.OrdinalIgnoreCase) &&
                   leaderboard.difficulty == difficulty;
        }

        private static string CreateBeatLeaderMapKey(string songHash, string modeName, int difficulty)
        {
            if (string.IsNullOrWhiteSpace(songHash) || string.IsNullOrWhiteSpace(modeName))
                return null;

            return $"{songHash.Trim().ToUpperInvariant()}|{modeName.Trim()}|{difficulty}";
        }

        private static bool TryMapDifficultyToBeatLeaderValue(string difficultyName, out int difficulty)
        {
            switch (difficultyName)
            {
                case "Easy":
                    difficulty = 1;
                    return true;
                case "Normal":
                    difficulty = 3;
                    return true;
                case "Hard":
                    difficulty = 5;
                    return true;
                case "Expert":
                    difficulty = 7;
                    return true;
                case "ExpertPlus":
                    difficulty = 9;
                    return true;
                default:
                    difficulty = 0;
                    return false;
            }
        }

        private LeaderboardJson BuildVirtualLeaderboardIfNeeded(int leagueId, VirtualLeagueState state, LeaderboardJson sourceLeaderboard, bool force)
        {
            if (sourceLeaderboard == null)
                return null;
            if (!force && !state.Dirty && state.CachedVirtualLeaderboard != null && state.SourceLeaderboardTimestamp == sourceLeaderboard.jbslViewerGetTime)
                return state.CachedVirtualLeaderboard;

            // Match jbsl-web behavior: virtual participation changes the ranking order,
            // but it does not increase league.player.count(), so the base pos stays the same.
            var sourceBasePos = Leaderboard.InferLeagueBasePosFromMaps(sourceLeaderboard);
            var maxValid = Math.Max(this._activeLeague.GetLeagueMaxValid(leagueId), 0);
            var maps = new List<Map>();
            var totalRankLookup = new Dictionary<string, List<Score>>(StringComparer.Ordinal);
            var firstAppearance = new Dictionary<string, int>(StringComparer.Ordinal);
            var nextAppearance = 0;

            foreach (var sourceMap in sourceLeaderboard.maps ?? new List<Map>())
            {
                if (sourceMap == null)
                    continue;

                var mapState = string.IsNullOrEmpty(sourceMap.lid) ? null : state.GetOrCreateMapState(sourceMap.lid);
                var selectedMaxScore = this.ResolveSelectedMaxScore(mapState);
                var webMaxScore = mapState?.WebMaxScore ?? 0;
                var recreatedMap = new Map
                {
                    title = sourceMap.title,
                    lid = sourceMap.lid,
                    hash = sourceMap.hash,
                    scores = new List<Score>(),
                };

                var scoreEntries = new List<VirtualScoreEntry>();
                if (sourceMap.scores != null)
                {
                    foreach (var sourceScore in sourceMap.scores)
                    {
                        if (sourceScore == null)
                            continue;

                        var rawScore = RecoverRawScore(sourceScore.acc, webMaxScore);
                        var clonedScore = CloneScore(sourceScore);
                        clonedScore.rawScore = rawScore;
                        scoreEntries.Add(new VirtualScoreEntry(clonedScore, rawScore, sourceScore.standing));
                    }
                }

                if (mapState != null && mapState.SelfScore.HasScore && !string.IsNullOrEmpty(this._selfSid))
                {
                    var selfScore = new Score
                    {
                        sid = this._selfSid,
                        name = this.GetSelfDisplayName(),
                        miss = mapState.SelfScore.Miss,
                        rawScore = mapState.SelfScore.RawScore,
                    };
                    selfScore.acc = this.CalculateAccuracy(selfScore.rawScore, selectedMaxScore, webMaxScore, 0f);
                    scoreEntries.Add(new VirtualScoreEntry(selfScore, selfScore.rawScore, int.MaxValue));
                }

                scoreEntries = scoreEntries
                    .OrderByDescending(x => x.RawScore)
                    .ThenBy(x => x.SortOrder)
                    .ToList();

                for (var index = 0; index < scoreEntries.Count; index++)
                {
                    var score = scoreEntries[index].Score;
                    score.standing = index + 1;
                    score.pos = sourceBasePos + Slope(index + 1);
                    recreatedMap.scores.Add(score);

                    if (!totalRankLookup.TryGetValue(score.sid, out var totalScores))
                    {
                        totalScores = new List<Score>();
                        totalRankLookup.Add(score.sid, totalScores);
                        firstAppearance[score.sid] = nextAppearance++;
                    }

                    totalScores.Add(score);
                }

                maps.Add(recreatedMap);
            }

            var totalRank = new List<Score>();
            foreach (var totalScorePair in totalRankLookup)
            {
                var validScores = totalScorePair.Value
                    .OrderByDescending(x => x.pos)
                    .ThenByDescending(x => x.acc)
                    .Take(maxValid)
                    .ToList();
                if (validScores.Count <= 0)
                    continue;

                totalRank.Add(new Score
                {
                    sid = totalScorePair.Key,
                    name = validScores[0].name,
                    pos = validScores.Sum(x => x.pos),
                    acc = validScores.Average(x => x.acc),
                });
            }

            totalRank = totalRank
                .OrderByDescending(x => x.pos)
                .ThenByDescending(x => x.acc)
                .ThenBy(x => firstAppearance.TryGetValue(x.sid, out var order) ? order : int.MaxValue)
                .ToList();
            for (var index = 0; index < totalRank.Count; index++)
                totalRank[index].standing = index + 1;

            state.CachedVirtualLeaderboard = new LeaderboardJson
            {
                total_rank = totalRank,
                maps = maps,
                jbslViewerGetTime = sourceLeaderboard.jbslViewerGetTime,
            };
            state.SourceLeaderboardTimestamp = sourceLeaderboard.jbslViewerGetTime;
            state.Dirty = false;
            return state.CachedVirtualLeaderboard;
        }

        private bool TryGetLeagueContext(int leagueId, out LeagueJson league, out LeaderboardJson sourceLeaderboard)
        {
            sourceLeaderboard = this._leaderboard.GetLeaderboardData(leagueId);
            league = this._activeLeague._leagues?.FirstOrDefault(x => x.id == leagueId);
            return league != null && sourceLeaderboard != null;
        }

        private bool IsSelfInTotal(LeaderboardJson sourceLeaderboard)
        {
            if (string.IsNullOrEmpty(this._selfSid) || sourceLeaderboard?.total_rank == null)
                return false;
            return sourceLeaderboard.total_rank.Any(x => x != null && string.Equals(x.sid, this._selfSid, StringComparison.Ordinal));
        }

        private VirtualLeagueState GetOrCreateState(int leagueId)
        {
            if (this._leagueStates.TryGetValue(leagueId, out var state))
                return state;

            state = new VirtualLeagueState(leagueId);
            this._leagueStates.Add(leagueId, state);
            return state;
        }

        private int ResolveSelectedMaxScore(VirtualMapState mapState)
        {
            var webMaxScore = mapState?.WebMaxScore ?? 0;
            if (PluginConfig.Instance.useScoreSaberMaxScoreForVirtualLeague && mapState?.ScoreSaberMaxScore > 0)
                return mapState.ScoreSaberMaxScore.Value;
            if (webMaxScore > 0)
                return webMaxScore;
            return mapState?.ScoreSaberMaxScore ?? 0;
        }

        private float CalculateAccuracy(int rawScore, int selectedMaxScore, int webMaxScore, float fallbackAccuracy)
        {
            var maxScore = selectedMaxScore > 0 ? selectedMaxScore : webMaxScore;
            if (maxScore <= 0)
                return fallbackAccuracy;
            return (float)rawScore / maxScore * 100f;
        }

        private static int RecoverRawScore(float accuracy, int webMaxScore)
        {
            if (webMaxScore <= 0)
                return 0;

            var rawScore = (int)Math.Round(accuracy / 100f * webMaxScore, MidpointRounding.AwayFromZero);
            if (rawScore < 0)
                return 0;
            return rawScore > webMaxScore ? webMaxScore : rawScore;
        }

        private static Score CloneScore(Score sourceScore)
        {
            return new Score
            {
                standing = sourceScore.standing,
                sid = sourceScore.sid,
                name = sourceScore.name,
                acc = sourceScore.acc,
                pos = sourceScore.pos,
                miss = sourceScore.miss,
                rawScore = sourceScore.rawScore,
            };
        }

        private string GetSelfDisplayName()
        {
            return string.IsNullOrWhiteSpace(this._selfName) ? (this._selfSid ?? "You") : this._selfName;
        }

        private void LogMaxScoreDifference(VirtualMapState mapState)
        {
            if (mapState == null || mapState.HasLoggedMaxScoreDifference)
                return;
            if (!mapState.ScoreSaberMaxScore.HasValue || mapState.WebMaxScore <= 0)
                return;
            if (mapState.ScoreSaberMaxScore.Value == mapState.WebMaxScore)
                return;

            mapState.HasLoggedMaxScoreDifference = true;
            Plugin.Log?.Warn($"Virtual participation maxScore mismatch on lid {mapState.Lid}: ScoreSaber={mapState.ScoreSaberMaxScore.Value}, JBSL={mapState.WebMaxScore}");
        }

        private static int BuildWebMaxScore(int notes)
        {
            var maxScore = 0;
            var remaining = notes;

            var multiplyCount = 1;
            while (remaining > 0 && multiplyCount > 0)
            {
                maxScore += 115;
                remaining--;
                multiplyCount--;
            }

            multiplyCount = 4;
            while (remaining > 0 && multiplyCount > 0)
            {
                maxScore += 115 * 2;
                remaining--;
                multiplyCount--;
            }

            multiplyCount = 8;
            while (remaining > 0 && multiplyCount > 0)
            {
                maxScore += 115 * 4;
                remaining--;
                multiplyCount--;
            }

            while (remaining > 0)
            {
                maxScore += 115 * 8;
                remaining--;
            }

            return maxScore;
        }

        private static int Slope(int n)
        {
            if (n == 1)
                return 0;
            if (n == 2)
                return -3;
            return -(n + 2);
        }

        private void RaiseVirtualLeaderboardUpdated(int leagueId)
        {
            this.VirtualLeaderboardUpdated?.Invoke(leagueId);
        }

        private void RaiseVirtualLeaderboardUpdated(IEnumerable<int> leagueIds)
        {
            if (leagueIds == null)
                return;
            foreach (var leagueId in leagueIds.Distinct().ToList())
                this.RaiseVirtualLeaderboardUpdated(leagueId);
        }

        private void RaiseAvailabilityChanged(int leagueId)
        {
            this.VirtualAvailabilityChanged?.Invoke(leagueId);
        }

        private void RaiseAvailabilityChanged(IEnumerable<int> leagueIds)
        {
            if (leagueIds == null)
                return;
            foreach (var leagueId in leagueIds.Distinct().ToList())
                this.RaiseAvailabilityChanged(leagueId);
        }

        private void UpdateProgress(VirtualLeagueState state, int completedMaps, int totalMaps, bool isActive)
        {
            if (state == null)
                return;

            state.ProgressCompleted = Math.Max(0, completedMaps);
            state.ProgressTotal = Math.Max(0, totalMaps);
            state.ProgressActive = isActive && state.ProgressTotal > 0;
            this.VirtualParticipationProgressChanged?.Invoke(state.LeagueId, state.ProgressCompleted, state.ProgressTotal, state.ProgressActive);
        }

        protected virtual void Dispose(bool disposing)
        {
            if (this._disposedValue)
                return;

            if (disposing)
                this._updateSemaphore.Dispose();

            this._disposedValue = true;
        }

        public void Dispose()
        {
            this.Dispose(true);
            GC.SuppressFinalize(this);
        }
    }

    internal sealed class VirtualLeagueState
    {
        public int LeagueId { get; }
        public int PlaylistId { get; set; }
        public bool PlaylistSongsLoaded { get; set; }
        public bool Initialized { get; set; }
        public bool IsEnabled { get; set; }
        public bool Dirty { get; set; } = true;
        public DateTime SourceLeaderboardTimestamp { get; set; }
        public LeaderboardJson CachedVirtualLeaderboard { get; set; }
        public int ProgressCompleted { get; set; }
        public int ProgressTotal { get; set; }
        public bool ProgressActive { get; set; }
        public Dictionary<string, PlaylistSongJson> PlaylistSongsByLid { get; } = new Dictionary<string, PlaylistSongJson>(StringComparer.Ordinal);
        public Dictionary<string, VirtualMapState> MapStates { get; } = new Dictionary<string, VirtualMapState>(StringComparer.Ordinal);

        public VirtualLeagueState(int leagueId)
        {
            this.LeagueId = leagueId;
        }

        public VirtualMapState GetOrCreateMapState(string lid)
        {
            if (string.IsNullOrEmpty(lid))
                return null;
            if (this.MapStates.TryGetValue(lid, out var mapState))
                return mapState;

            mapState = new VirtualMapState(lid);
            this.MapStates.Add(lid, mapState);
            return mapState;
        }
    }

    internal sealed class VirtualMapState
    {
        public string Lid { get; }
        public string Title { get; set; }
        public string Hash { get; set; }
        public string Diff { get; set; }
        public string Characteristic { get; set; }
        public int Notes { get; set; }
        public int WebMaxScore { get; set; }
        public bool ScoreSaberInfoFetched { get; set; }
        public int? ScoreSaberMaxScore { get; set; }
        public bool InitialSelfScoreFetched { get; set; }
        public bool HasLoggedMaxScoreDifference { get; set; }
        public VirtualSelfScore SelfScore { get; set; } = new VirtualSelfScore();

        public VirtualMapState(string lid)
        {
            this.Lid = lid;
        }
    }

    internal sealed class VirtualSelfScore
    {
        public bool HasScore { get; set; }
        public int RawScore { get; set; }
        public int Miss { get; set; }
    }

    internal sealed class VirtualScoreEntry
    {
        public Score Score { get; }
        public int RawScore { get; }
        public int SortOrder { get; }

        public VirtualScoreEntry(Score score, int rawScore, int sortOrder)
        {
            this.Score = score;
            this.RawScore = rawScore;
            this.SortOrder = sortOrder;
        }
    }
}

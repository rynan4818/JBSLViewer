using System;
using JBSLViewer.Qualifier.Core.Contracts;

namespace JBSLViewer.Qualifier
{
    // App-scoped navigation data only. Challenge ownership remains in QualifierRuntime.
    public sealed class QualifierRoomState
    {
        public int LeagueId { get; private set; }
        public MapKey Map { get; private set; }
        public long Generation { get; private set; }
        public bool IsOpen { get; private set; }
        public bool LaunchPending { get; private set; }
        public bool Practice { get; private set; }
        public bool GameplaySeen { get; private set; }
        public bool ReturnReady { get; private set; }
        public bool ShowingResults { get; private set; }
        public long LaunchId { get; private set; }
        public string Notice { get; set; }
        public int SongIndex { get; set; }
        public int LeagueIndex { get; set; }

        public long Open(int leagueId = 0, MapKey map = null)
        {
            IsOpen = true;
            LeagueId = leagueId;
            Map = map?.Copy();
            SongIndex = LeagueIndex = 0;
            return ++Generation;
        }
        public long Select(int leagueId, MapKey map)
        {
            LeagueId = leagueId;
            Map = map?.Copy();
            Notice = null;
            return ++Generation;
        }
        public bool IsCurrent(long generation) => IsOpen && Generation == generation;
        public bool BeginLaunch(bool practice)
        {
            if (!IsOpen || LaunchPending || ShowingResults || LeagueId <= 0 || Map == null) return false;
            Practice = practice;
            LaunchPending = true;
            GameplaySeen = ReturnReady = false;
            ++LaunchId;
            return true;
        }
        public bool IsCurrentLaunch(long id) => IsOpen && LaunchPending && LaunchId == id;
        public bool CompleteLaunch(long id, bool showResults)
        {
            if (!IsCurrentLaunch(id)) return false;
            Resume();
            ShowingResults = showResults;
            return true;
        }
        public void RestartAsPractice(long id)
        {
            if (!IsCurrentLaunch(id)) return;
            Practice = true;
            GameplaySeen = ReturnReady = false;
        }
        public void GameplayStarted()
        {
            if (LaunchPending) { GameplaySeen = true; ReturnReady = false; }
        }
        public void GameplayFinished()
        {
            if (LaunchPending && GameplaySeen) ReturnReady = true;
        }
        public void LaunchFailed(string message)
        {
            if (!LaunchPending) return;
            Notice = message;
            ReturnReady = true;
        }
        public void Resume()
        {
            IsOpen = true;
            LaunchPending = GameplaySeen = ReturnReady = Practice = ShowingResults = false;
            ++Generation;
        }
        public void Close()
        {
            IsOpen = LaunchPending = GameplaySeen = ReturnReady = Practice = ShowingResults = false;
            LeagueId = 0;
            Map = null;
            Notice = null;
            ++Generation;
            SongIndex = LeagueIndex = 0;
        }
    }
}

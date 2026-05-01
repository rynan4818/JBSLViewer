using System.Collections.Generic;

namespace JBSLViewer.Models.ScoreSaber
{
    public class ScoreSaberLeaderboardScoresPageJson
    {
        public List<ScoreSaberLeaderboardScoreJson> scores { get; set; }
        public ScoreSaberPageMetadataJson metadata { get; set; }
        public string errorMessage { get; set; }
    }

    public class ScoreSaberLeaderboardScoreJson
    {
        public ScoreSaberLeaderboardPlayerInfoJson leaderboardPlayerInfo { get; set; }
        public int modifiedScore { get; set; }
        public int badCuts { get; set; }
        public int missedNotes { get; set; }
    }

    public class ScoreSaberLeaderboardPlayerInfoJson
    {
        public string id { get; set; }
        public string name { get; set; }
    }

    public class ScoreSaberPageMetadataJson
    {
        public int total { get; set; }
        public int page { get; set; }
        public int itemsPerPage { get; set; }
    }
}

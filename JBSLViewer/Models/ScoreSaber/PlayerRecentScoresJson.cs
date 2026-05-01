using System.Collections.Generic;

namespace JBSLViewer.Models.ScoreSaber
{
    public class ScoreSaberPlayerRecentScoresJson
    {
        public List<ScoreSaberPlayerRecentScoreEntryJson> playerScores { get; set; }
        public ScoreSaberPageMetadataJson metadata { get; set; }
    }

    public class ScoreSaberPlayerRecentScoreEntryJson
    {
        public ScoreSaberPlayerRecentScoreJson score { get; set; }
        public ScoreSaberRecentLeaderboardJson leaderboard { get; set; }
    }

    public class ScoreSaberPlayerRecentScoreJson
    {
        public int modifiedScore { get; set; }
        public int badCuts { get; set; }
        public int missedNotes { get; set; }
        public string timeSet { get; set; }
    }

    public class ScoreSaberRecentLeaderboardJson
    {
        public int id { get; set; }
        public string songHash { get; set; }
        public Difficulty difficulty { get; set; }
        public int maxScore { get; set; }
    }
}

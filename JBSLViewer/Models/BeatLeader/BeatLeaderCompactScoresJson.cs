using System.Collections.Generic;

namespace JBSLViewer.Models.BeatLeader
{
    public class BeatLeaderCompactScoresJson
    {
        public BeatLeaderCompactMetadataJson metadata { get; set; }
        public List<BeatLeaderCompactScoreEntryJson> data { get; set; }
    }

    public class BeatLeaderCompactMetadataJson
    {
        public int itemsPerPage { get; set; }
        public int page { get; set; }
        public int total { get; set; }
    }

    public class BeatLeaderCompactScoreEntryJson
    {
        public BeatLeaderCompactScoreJson score { get; set; }
        public BeatLeaderCompactLeaderboardJson leaderboard { get; set; }
    }

    public class BeatLeaderCompactScoreJson
    {
        public int modifiedScore { get; set; }
        public int badCuts { get; set; }
        public int missedNotes { get; set; }
        public long epochTime { get; set; }
    }

    public class BeatLeaderCompactLeaderboardJson
    {
        public string songHash { get; set; }
        public string modeName { get; set; }
        public int difficulty { get; set; }
    }
}

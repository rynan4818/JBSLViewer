namespace JBSLViewer.Models.BeatLeader
{
    public class BeatLeaderScoreJson
    {
        public string id { get; set; }
        public int baseScore { get; set; }
        public int modifiedScore { get; set; }
        public float accuracy { get; set; }
        public int badCuts { get; set; }
        public int missedNotes { get; set; }
    }
}

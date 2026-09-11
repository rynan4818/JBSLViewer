namespace JBSLViewer.Qualifier
{
    // One immutable selection owns the exact key and loaded level data used at launch.
    public sealed class QualifierBeatmap
    {
        public BeatmapKey Key { get; }
        public BeatmapLevel Level { get; }
        public IBeatmapLevelData Data { get; }
        public BeatmapDataBasicInfo BasicInfo { get; }
        // 1.37.1 has no ContainsBeatmapData; the native loader returns null for a missing key's JSON.
        public bool IsReady => Key.IsValid() && Level != null && Data != null && BasicInfo != null
            && Level.levelID == Key.levelId;

        public QualifierBeatmap(BeatmapKey key, BeatmapLevel level, IBeatmapLevelData data, BeatmapDataBasicInfo basicInfo = null)
        { Key = key; Level = level; Data = data; BasicInfo = basicInfo; }
    }
}

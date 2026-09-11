namespace JBSLViewer.Qualifier
{
    // One immutable selection owns the exact key and loaded level data used at launch.
    public sealed class QualifierBeatmap
    {
        public BeatmapKey Key { get; }
        public BeatmapLevel Level { get; }
        public IBeatmapLevelData Data { get; }
        public BeatmapDataBasicInfo BasicInfo { get; }
        public bool IsReady => Key.IsValid() && Level != null && Data != null
            && Level.levelID == Key.levelId && BasicInfo != null && Data.ContainsBeatmapData(Key);

        public QualifierBeatmap(BeatmapKey key, BeatmapLevel level, IBeatmapLevelData data, BeatmapDataBasicInfo basicInfo = null)
        { Key = key; Level = level; Data = data; BasicInfo = basicInfo; }
    }
}

using System;
using System.Reflection;
using JBSLViewer.Qualifier.Replay;

namespace JBSLViewer.Qualifier.Tests
{
    internal static class ReplayModeScenarios
    {
        internal static void Run()
        {
            InstancePlugin.Current = new InstancePlugin();
            Program.Check(ReplayModeDetector.ScoreSaberBlockingReason(typeof(InstancePlugin)) == null, "ScoreSaber instance API allows normal play");
            InstancePlugin.Current.State.IsPlaybackEnabled = true;
            Program.Check(ReplayModeDetector.ScoreSaberBlockingReason(typeof(InstancePlugin)) == "replay_playback", "ScoreSaber instance API blocks replay playback");
            InstancePlugin.Current = null;
            Program.Check(ReplayModeDetector.ScoreSaberBlockingReason(typeof(InstancePlugin)) == "scoresaber_replay_state_unavailable", "ScoreSaber initialization remains fail closed");
            StaticPlugin.State = new ReplayState();
            Program.Check(ReplayModeDetector.ScoreSaberBlockingReason(typeof(StaticPlugin)) == null, "ScoreSaber older static API allows normal play");
            StaticPlugin.State.IsPlaybackEnabled = true;
            Program.Check(ReplayModeDetector.ScoreSaberBlockingReason(typeof(StaticPlugin)) == "replay_playback", "ScoreSaber older static API blocks replay playback");
            StaticPlugin.State = null;
            Program.Check(ReplayModeDetector.ScoreSaberBlockingReason(typeof(StaticPlugin)) == "scoresaber_replay_state_unavailable", "ScoreSaber missing replay state remains fail closed");
            Program.Check(ReplayModeDetector.ScoreSaberBlockingReason(typeof(ThrowingPlugin)) == "scoresaber_replay_state_unavailable", "ScoreSaber getter failure remains fail closed");
            Program.Check(ReplayModeDetector.ScoreSaberBlockingReason(typeof(object)) == "scoresaber_replay_state_unavailable", "ScoreSaber incompatible API remains fail closed");
            Program.Check(ReplayModeDetector.BlockingReason() == null, "ScoreSaber not installed does not block challenges");
        }
        private sealed class ReplayState { internal bool IsPlaybackEnabled; }
        private sealed class InstancePlugin
        {
            internal static InstancePlugin Current;
            internal readonly ReplayState State = new ReplayState();
            private static InstancePlugin Instance => Current;
            private ReplayState ReplayState => State;
        }
        private static class StaticPlugin
        {
            internal static ReplayState State;
            private static ReplayState ReplayState => State;
        }
        private static class ThrowingPlugin { private static ReplayState ReplayState => throw new InvalidOperationException(); }
    }
}

// The game-free test executable only supplies the plugin catalog. The actual detector is linked above.
namespace IPA.Loader
{
    internal sealed class PluginMetadata { public Assembly Assembly { get; set; } }
    internal static class PluginManager { internal static PluginMetadata GetPluginFromId(string id) => null; }
}

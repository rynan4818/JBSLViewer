using System;
using System.Reflection;
using IPA.Loader;

namespace JBSLViewer.Qualifier.Replay
{
    public static class ReplayModeDetector
    {
        // Reads real playback state; never invokes another mod's gameplay patches.
        public static string BlockingReason()
        {
            try
            {
                var leader = PluginManager.GetPluginFromId("BeatLeader");
                if (leader != null)
                {
                    var property = leader.Assembly.GetType("BeatLeader.Replayer.ReplayerLauncher")?
                        .GetProperty("IsStartedAsReplay", BindingFlags.Static | BindingFlags.Public);
                    if (property == null) return "beatleader_replay_state_unavailable";
                    if ((bool)property.GetValue(null)) return "replay_playback";
                }
                var saber = PluginManager.GetPluginFromId("ScoreSaber");
                if (saber != null)
                {
                    var property = saber.Assembly.GetType("ScoreSaber.Plugin")?
                        .GetProperty("ReplayState", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
                    if (property == null) return "scoresaber_replay_state_unavailable";
                    var state = property.GetValue(null);
                    if (state == null) return "scoresaber_replay_state_unavailable";
                    var enabled = state.GetType().GetField("IsPlaybackEnabled", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                    if (enabled == null) return "scoresaber_replay_state_unavailable";
                    if ((bool)enabled.GetValue(state)) return "replay_playback";
                }
                return null;
            }
            catch (Exception) { return "replay_state_unavailable"; }
        }
    }
}

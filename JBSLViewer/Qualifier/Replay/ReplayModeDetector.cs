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
                    var reason = ScoreSaberBlockingReason(saber.Assembly.GetType("ScoreSaber.Plugin"));
                    if (reason != null) return reason;
                }
                return null;
            }
            catch (Exception) { return "replay_state_unavailable"; }
        }

        internal static string ScoreSaberBlockingReason(Type pluginType)
        {
            try
            {
                var replay = pluginType?.GetProperty("ReplayState", BindingFlags.Static | BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                if (replay?.GetGetMethod(true) == null) return "scoresaber_replay_state_unavailable";
                object instance = null;
                // BS1.29.1 has both the older static API and the newer instance API in circulation.
                if (!replay.GetGetMethod(true).IsStatic)
                {
                    instance = pluginType.GetProperty("Instance", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(null);
                    if (instance == null) return "scoresaber_replay_state_unavailable";
                }
                var state = replay.GetValue(instance);
                if (state == null) return "scoresaber_replay_state_unavailable";
                var enabled = state.GetType().GetField("IsPlaybackEnabled", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                if (enabled == null || enabled.FieldType != typeof(bool)) return "scoresaber_replay_state_unavailable";
                return (bool)enabled.GetValue(state) ? "replay_playback" : null;
            }
            catch (Exception) { return "scoresaber_replay_state_unavailable"; }
        }
    }
}

// Game-free collaborators for the linked production direct-play controller and adapter.
// These tests exercise callback ordering and ownership, not Unity rendering or Harmony.
using System;
using System.Collections.Generic;
using System.Reflection;
using JBSLViewer.Qualifier.Core;
using JBSLViewer.Qualifier.Core.Contracts;

namespace Zenject
{
    public sealed class DiContainer { }
    public interface IInitializable { void Initialize(); }
    public interface ITickable { void Tick(); }
}
namespace HarmonyLib
{
    [AttributeUsage(AttributeTargets.Class)] public sealed class HarmonyPatch : Attribute { public HarmonyPatch(Type type, string method) { } }
    public static class AccessTools
    {
        public static MethodInfo DeclaredMethod(Type type, string name) => type.GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
    }
}
public class SinglePlayerLevelSelectionFlowCoordinator
{
    public event Action<SinglePlayerLevelSelectionFlowCoordinator> didFinishEvent;
    public int PlayCalls;
    public Action OnPlay;
    protected void ActionButtonWasPressed() { PlayCalls++; OnPlay?.Invoke(); }
    public void StartLevel() { }
    public void FinishMenu() => didFinishEvent?.Invoke(this);
}
public sealed class SoloFreePlayFlowCoordinator : SinglePlayerLevelSelectionFlowCoordinator { }
public enum BeatmapDifficulty { Easy, Normal, Hard, Expert, ExpertPlus }
public sealed class BeatmapCharacteristicSO { public string serializedName = "Standard"; }
public struct BeatmapKey
{
    public string levelId;
    public BeatmapCharacteristicSO beatmapCharacteristic;
    public BeatmapDifficulty difficulty;
    public BeatmapKey(string level, BeatmapCharacteristicSO characteristic, BeatmapDifficulty selectedDifficulty)
    { levelId = level; beatmapCharacteristic = characteristic; difficulty = selectedDifficulty; }
    public bool IsValid() => !string.IsNullOrEmpty(levelId) && beatmapCharacteristic != null;
}
public sealed class BeatmapLevel
{
    public string levelID = "custom_level_0123456789ABCDEF0123456789ABCDEF01234567";
    public readonly ColorScheme MapColors = new ColorScheme();
    public ColorScheme GetColorScheme(BeatmapCharacteristicSO characteristic, BeatmapDifficulty difficulty) => MapColors;
}
public interface IBeatmapLevelData { }
public sealed class TestLevelData : IBeatmapLevelData { }
public sealed class BeatmapDataBasicInfo { }
public sealed class EnvironmentsListModel { }
public static class RecordingToolManager { public struct SetupData { } }
public sealed class OverrideEnvironmentSettings { }
public sealed class ColorScheme { }
public sealed class GameplayModifiers { }
public sealed class PlayerSpecificSettings { }
public sealed class PracticeSettings { }
public sealed class ColorSchemesSettings
{
    public readonly ColorScheme Color = new ColorScheme();
    public ColorScheme GetOverrideColorScheme() => Color;
}
public sealed class GameplaySetupViewController
{
    public readonly OverrideEnvironmentSettings environmentOverrideSettings = new OverrideEnvironmentSettings();
    public readonly ColorSchemesSettings colorSchemesSettings = new ColorSchemesSettings();
    public readonly GameplayModifiers gameplayModifiers = new GameplayModifiers();
    public readonly PlayerSpecificSettings playerSettings = new PlayerSpecificSettings();
}
public interface IReadonlyBeatmapData { }
public sealed class TestBeatmapData : IReadonlyBeatmapData { }
public class LevelScenesTransitionSetupDataSO { }
public sealed class StandardLevelScenesTransitionSetupDataSO : LevelScenesTransitionSetupDataSO
{
    public IReadonlyBeatmapData transformedBeatmapData = new TestBeatmapData();
}
public sealed class LevelCompletionResults
{
    public enum LevelEndStateType { Incomplete, Cleared, Failed }
    public enum LevelEndAction { None, Quit, Restart }
    public LevelEndStateType levelEndStateType;
    public LevelEndAction levelEndAction;
}
public sealed class MenuTransitionsHelper
{
    public sealed class Invocation
    {
        public string Mode;
        public BeatmapKey Key;
        public BeatmapLevel Level;
        public IBeatmapLevelData Data;
        public OverrideEnvironmentSettings Environment;
        public ColorScheme Colors;
        public ColorScheme MapColors;
        public EnvironmentsListModel Environments;
        public GameplayModifiers Modifiers;
        public PlayerSpecificSettings Settings;
        public PracticeSettings Practice;
        public Action<StandardLevelScenesTransitionSetupDataSO, LevelCompletionResults> Finished;
        public Action<LevelScenesTransitionSetupDataSO, LevelCompletionResults> Restarted;
    }
    public readonly List<Invocation> Calls = new List<Invocation>();
    public Action<Invocation> OnStart;
    public void StartStandardLevel(string mode, in BeatmapKey key, BeatmapLevel level, IBeatmapLevelData data,
        OverrideEnvironmentSettings environment, ColorScheme colors, ColorScheme mapColors, GameplayModifiers modifiers,
        PlayerSpecificSettings settings, PracticeSettings practice, EnvironmentsListModel environments,
        string backButtonText, bool testSounds, bool paused, Action beforeSwitch, Action<Zenject.DiContainer> afterSwitch,
        Action<StandardLevelScenesTransitionSetupDataSO, LevelCompletionResults> finished,
        Action<LevelScenesTransitionSetupDataSO, LevelCompletionResults> restarted, RecordingToolManager.SetupData? recording)
    {
        var call = new Invocation { Mode = mode, Key = key, Level = level, Data = data, Environment = environment,
            Colors = colors, MapColors = mapColors, Environments = environments,
            Modifiers = modifiers, Settings = settings, Practice = practice, Finished = finished, Restarted = restarted };
        Calls.Add(call);
        OnStart?.Invoke(call);
    }
}
namespace JBSLViewer.Qualifier
{
    public sealed class QualifierRuntime
    {
        public bool AllowStart = true, SelectionLocked, SceneTransitioning;
        public ChallengeContext ActiveChallenge;
        public int OrdinaryStarts, OrdinaryRestarts;
        public bool MenuCanStart(ChallengeContext context) => AllowStart;
        public void OrdinaryPlayRequested() { OrdinaryStarts++; }
        public void OrdinaryRestartDetected() { OrdinaryRestarts++; }
    }
    public sealed class SubmissionEligibilityTracker
    {
        public int Tracks, Detaches;
        private SubmissionHistory _active;
        public void Track(SubmissionHistory history)
        {
            if (_active != null && !ReferenceEquals(_active, history)) throw new InvalidOperationException("Already tracking another play");
            _active = history; Tracks++;
        }
        public void Detach(SubmissionHistory history)
        {
            if (_active != null && ReferenceEquals(_active, history)) { _active = null; Detaches++; }
        }
    }
    public sealed class QualifierMenuController
    {
        public static QualifierMenuController Instance => null;
        public void ApplyLock() { }
    }
    public static class QualifierGameplayObserver
    {
        public static int MenuReturns;
        public static MapKey ReadMap(BeatmapKey beatmap) => MapKey.Create(beatmap.levelId.Substring(13), beatmap.beatmapCharacteristic.serializedName, beatmap.difficulty.ToString());
        public static void MenuActivated() { MenuReturns++; }
    }
}
namespace JBSLViewer.Qualifier.UI
{
    public sealed class QualifierMenuEntry
    {
        private readonly QualifierRoomState _room;
        public QualifierBeatmap SelectedBeatmap { get; set; }
        public bool Ready = true, MenuVisible = true;
        public bool SelectionReady => Ready && _room.IsOpen && !_room.ShowingResults;
        public bool CanReceiveDirectResult => _room.IsOpen && MenuVisible;
        public bool OwnsSelection { get; set; } = true;
        public readonly List<QualifierDirectPlayResult> Returns = new List<QualifierDirectPlayResult>();
        public QualifierMenuEntry(QualifierRoomState room, QualifierBeatmap map) { _room = room; SelectedBeatmap = map; }
        public bool BeginDirectLaunch(bool practice) => SelectionReady && _room.BeginLaunch(practice);
        public void ShowDirectResult(QualifierDirectPlayResult result) { Returns.Add(result); }
    }
}

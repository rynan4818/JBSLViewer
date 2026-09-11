// Submission observation adapted from BeatLeader:
// https://github.com/BeatLeader/beatleader-mod/blob/1291supportx/LICENSE
// Copyright (c) 2023 BeatLeader. MIT License; see THIRD-PARTY-NOTICES.txt in the distribution.
using System;
using System.Collections.Generic;
using System.Reflection;
using HarmonyLib;
using SiraUtil.Submissions;

namespace JBSLViewer.Qualifier
{
    [HarmonyPatch(typeof(SinglePlayerLevelSelectionFlowCoordinator), "LevelSelectionFlowCoordinatorDidActivate")]
    internal static class QualifierMenuReturnPatch
    { private static void Postfix() { QualifierGameplayObserver.MenuActivated(); QualifierRuntime.Instance?.StandardGameplayFinished(); } }
    [HarmonyPatch(typeof(StandardLevelScenesTransitionSetupDataSO), nameof(StandardLevelScenesTransitionSetupDataSO.Finish))]
    internal static class QualifierFinishPatch
    {
        // Snapshot before existing finish listeners can replace the gameplay scene.
        private static void Prefix(StandardLevelScenesTransitionSetupDataSO __instance, LevelCompletionResults levelCompletionResults)
        { QualifierGameplayObserver.Current?.Finish(__instance, levelCompletionResults); QualifierRuntime.Instance?.StandardGameplayFinished(); }
    }
    [HarmonyPatch(typeof(ScoreController), nameof(ScoreController.LateUpdate))]
    internal static class QualifierScoringPatch
    {
        private static bool Prefix(ScoreController __instance, AudioTimeSyncController ____audioTimeSyncController,
            List<float> ____sortedNoteTimesWithoutScoringElements, List<ScoringElement> ____sortedScoringElementsWithoutMultiplier)
        {
            if (QualifierGameplayObserver.Current?.AllowScoring(__instance, ____audioTimeSyncController,
                ____sortedNoteTimesWithoutScoringElements, ____sortedScoringElementsWithoutMultiplier) == false) return false;
            QualifierReplayRecorder.Current?.BeforeScoring(__instance, ____audioTimeSyncController,
                ____sortedNoteTimesWithoutScoringElements, ____sortedScoringElementsWithoutMultiplier);
            return true;
        }
    }
    [HarmonyPatch]
    internal static class QualifierSiraConstructorPatch
    {
        private static MethodBase TargetMethod() => AccessTools.GetDeclaredConstructors(typeof(Submission))[0];
        private static void Postfix(Submission __instance) { SubmissionEligibilityTracker.Register(__instance); }
    }
    [HarmonyPatch]
    internal static class QualifierSiraChangedPatch
    {
        private static IEnumerable<MethodBase> TargetMethods()
        {
            yield return AccessTools.Method(typeof(Submission), nameof(Submission.DisableScoreSubmission));
            yield return AccessTools.Method(typeof(Submission), nameof(Submission.Remove), new[] { typeof(Ticket) });
            yield return AccessTools.Method(typeof(Submission), nameof(Submission.Remove), new[] { typeof(string) });
        }
        private static void Postfix(Submission __instance) { SubmissionEligibilityTracker.Changed(__instance); }
    }
    [HarmonyPatch(typeof(Submission), nameof(Submission.Dispose))]
    internal static class QualifierSiraDisposePatch
    {
        private static void Postfix(Submission __instance) { SubmissionEligibilityTracker.Disposed(__instance); }
    }
    [HarmonyPatch]
    internal static class QualifierSiraSSSPatch
    {
        private static MethodBase TargetMethod() => AccessTools.Method("SiraUtil.Submissions.SubmissionDataContainer:SSS");
        private static void Prefix(bool __0) { SubmissionEligibilityTracker.StandardSubmissionObserved(__0, "sirautil_submission_disabled"); }
    }
    [HarmonyPatch]
    internal static class QualifierBsUtilsChangedPatch
    {
        private static IEnumerable<MethodBase> TargetMethods()
        {
            var type = typeof(BS_Utils.Gameplay.ScoreSubmission);
            yield return AccessTools.Method(type, "DisableSubmission");
            yield return AccessTools.Method(type, "ProlongedDisableSubmission");
            yield return AccessTools.Method(type, "RemoveProlongedDisable");
        }
        private static void Postfix() { SubmissionEligibilityTracker.Instance?.Refresh(); }
    }
    [HarmonyPatch]
    internal static class QualifierBsUtilsSubmissionPatch
    {
        private static MethodBase TargetMethod() => AccessTools.Method(typeof(BS_Utils.Gameplay.ScoreSubmission), "DisableScoreSaberScoreSubmission");
        private static void Prefix() { SubmissionEligibilityTracker.StandardSubmissionObserved(false, "bs_utils_submission_disabled"); }
    }
}

// Adapted from BeatLeader: https://github.com/BeatLeader/beatleader-mod/blob/1291supportx/LICENSE
// Copyright (c) 2023 BeatLeader. MIT License; see THIRD-PARTY-NOTICES.txt in the distribution.

using System;
using HarmonyLib;
using IPA.Utilities;
using UnityEngine;

namespace JBSLViewer.Qualifier.Replay
{
    [HarmonyPatch(typeof(SaberSwingRatingCounter), nameof(SaberSwingRatingCounter.ProcessNewData))]
	public static class PostSwingRatingEnhancerPatch
	{
        static void Prefix(SaberSwingRatingCounter __instance, BladeMovementDataElement newData, BladeMovementDataElement prevData, bool prevDataAreValid) {
            try { CapturePrefix(__instance, newData, prevData, prevDataAreValid); }
            catch (Exception ex) { QualifierReplayRecorder.Current?.RecordingError(ex); }
        }
        static void CapturePrefix(SaberSwingRatingCounter __instance, BladeMovementDataElement newData, BladeMovementDataElement prevData, bool prevDataAreValid) {
            if (!QualifierReplayRecorder.IsRecording) return;
            PostSwingRatingContainer container;
            if (!SwingRatingEnhancer.postSwingMap.ContainsKey(__instance))
            {
                container = new PostSwingRatingContainer();
                SwingRatingEnhancer.postSwingMap[__instance] = container;
            }
            else
            {
                container = SwingRatingEnhancer.postSwingMap[__instance];
            }

            container.AlreadyCut = __instance.GetField<bool, SaberSwingRatingCounter>("_notePlaneWasCut");
        }

		static void Postfix(SaberSwingRatingCounter __instance, BladeMovementDataElement newData, BladeMovementDataElement prevData, bool prevDataAreValid) {
            try { CapturePostfix(__instance, newData, prevData, prevDataAreValid); }
            catch (Exception ex) { QualifierReplayRecorder.Current?.RecordingError(ex); }
        }
        static void CapturePostfix(SaberSwingRatingCounter __instance, BladeMovementDataElement newData, BladeMovementDataElement prevData, bool prevDataAreValid) {
            if (!QualifierReplayRecorder.IsRecording) return;
            PostSwingRatingContainer container = SwingRatingEnhancer.postSwingMap[__instance];
            bool _rateAfterCut = __instance.GetField<bool, SaberSwingRatingCounter>("_rateAfterCut");
            Plane _notePlane = __instance.GetField<Plane, SaberSwingRatingCounter>("_notePlane");
            if (!container.AlreadyCut && !_notePlane.SameSide(newData.topPos, prevData.topPos))
            {
                Vector3 _cutTopPos = __instance.GetField<Vector3, SaberSwingRatingCounter>("_cutTopPos");
                Vector3 _cutBottomPos = __instance.GetField<Vector3, SaberSwingRatingCounter>("_cutBottomPos");
                Vector3 _afterCutTopPos = __instance.GetField<Vector3, SaberSwingRatingCounter>("_afterCutTopPos");
                Vector3 _afterCutBottomPos = __instance.GetField<Vector3, SaberSwingRatingCounter>("_afterCutBottomPos");

                float angleDiff = Vector3.Angle(_cutTopPos - _cutBottomPos, _afterCutTopPos - _afterCutBottomPos);

                if (_rateAfterCut)
                {
                    container.Value = SaberSwingRating.AfterCutStepRating(angleDiff, 0.0f);
                }
            }
            else
            {
                Vector3 _cutPlaneNormal = __instance.GetField<Vector3, SaberSwingRatingCounter>("_cutPlaneNormal");
                float normalDiff = Vector3.Angle(newData.segmentNormal, _cutPlaneNormal);
                if (_rateAfterCut)
                {
                    container.Value += SaberSwingRating.AfterCutStepRating(newData.segmentAngle, normalDiff);
                }
            }
        }
	}
}



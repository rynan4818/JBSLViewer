// Adapted from BeatLeader: https://github.com/BeatLeader/beatleader-mod/blob/1291supportx/LICENSE
// Copyright (c) 2023 BeatLeader. MIT License; see THIRD-PARTY-NOTICES.txt in the distribution.
using System.Collections.Generic;
using IPA.Utilities;
using UnityEngine;

namespace JBSLViewer.Qualifier.Replay {
    internal class PreSwingRatingContainer {
        public bool AlreadyCut { get; set; }
        public float Value { get; set; }
    }

    internal class PostSwingRatingContainer {
        public bool AlreadyCut { get; set; }
        public float Value { get; set; }
    }

    internal class SwingRatingEnhancer {
        public static Dictionary<ISaberMovementData, PreSwingRatingContainer> preSwingMap = new();
        public static Dictionary<SaberSwingRatingCounter, PostSwingRatingContainer> postSwingMap = new();

        public static void Reset(SaberSwingRatingCounter counter) {
            var saberMovementData = counter.GetField<ISaberMovementData, SaberSwingRatingCounter>("_saberMovementData");
            preSwingMap.Remove(saberMovementData);
            postSwingMap.Remove(counter);
        }

        public static void Enhance(Core.Replay.NoteCutInfo cutInfo, SaberSwingRatingCounter counter) {
            cutInfo.beforeCutRating = GetBeforeCutSwingRating(counter);
            cutInfo.afterCutRating = GetAfterCutSwingRating(counter);
        }

        private static float GetBeforeCutSwingRating(SaberSwingRatingCounter counter) {
            var saberMovementData = counter.GetField<ISaberMovementData, SaberSwingRatingCounter>("_saberMovementData");
            var realBeforeCutRating = counter.beforeCutRating;
            if (!preSwingMap.ContainsKey(saberMovementData)) return realBeforeCutRating;
            var unclampedBeforeCutRating = preSwingMap[saberMovementData].Value;
            return ChooseSwingRating(realBeforeCutRating, unclampedBeforeCutRating);
        }

        private static float GetAfterCutSwingRating(SaberSwingRatingCounter counter) {
            var realAfterCutRating = counter.afterCutRating;
            if (!postSwingMap.ContainsKey(counter)) return realAfterCutRating;
            var unclampedAfterCutRating = postSwingMap[counter].Value;
            return ChooseSwingRating(realAfterCutRating, unclampedAfterCutRating);
        }

        private static float ChooseSwingRating(float real, float unclamped) {
            return real < 1 ? real : Mathf.Max(real, unclamped);
        }
    }
}

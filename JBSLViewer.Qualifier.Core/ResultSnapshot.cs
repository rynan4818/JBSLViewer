using JBSLViewer.Qualifier.Core.Contracts;
namespace JBSLViewer.Qualifier.Core {
    public sealed class ResultSnapshot {
        public ResultMetadata Metadata { get; set; }
        public byte[] ReplayGzip { get; set; }
    }
    public static class QualifierResultFactory {
        public static ResultSnapshot Create(ChallengeContext context,string endType,ResultMetadata observed,byte[] replayGzip,IClock clock=null) {
            clock=clock??new SystemClock();
            var m=observed==null?new ResultMetadata {GameVersion=context.GameVersion}:StrictJson.Clone(observed);
            m.ClientResultId=context.ClientResultId;m.ChallengeId=context.ChallengeId;m.Map=context.Map.Copy();m.ClientVersion=context.ClientVersion;
            // Preserve Application.version, including its build suffix, to match the recorded BSOR.
            if(string.IsNullOrWhiteSpace(m.GameVersion)) m.GameVersion=string.IsNullOrWhiteSpace(context.GameVersion)?"1.42.0":context.GameVersion;
            var observedPlayCount=m.ScoreValidity?.PlayInstanceCount??0;
            m.EndType=endType;m.SubmissionEligibility=context.FrozenSubmission==null?context.Submission.ToContract():StrictJson.Clone(context.FrozenSubmission);m.Diagnostics=m.Diagnostics??new ResultDiagnostics();m.ScoreValidity=new ScoreValidity();
            var contextTiming=context.FrozenTiming??context.Timing;
            var t=m.Timing??new ResultTiming();t.ConfirmedAtClient=contextTiming.ConfirmedAtClient;t.ReserveResponseReceivedAtClient=contextTiming.ReserveResponseReceivedAtClient;t.StartedAtClient=contextTiming.StartedAtClient??t.StartedAtClient;t.LocalSongDurationSeconds=contextTiming.LocalSongDurationSeconds;t.SongSpeedMultiplier=contextTiming.SongSpeedMultiplier;
            t.ResultFinalizedAtClient=clock.UtcNow;m.Timing=t;
            m.EndSongTime=FiniteOrNull(m.EndSongTime);m.Energy=FiniteOrNull(m.Energy);
            t.LocalSongDurationSeconds=FiniteOrNull(t.LocalSongDurationSeconds);t.SongSpeedMultiplier=FiniteOrNull(t.SongSpeedMultiplier);t.TotalPauseSeconds=FiniteOrNull(t.TotalPauseSeconds);
            var reason=(string)null;
            switch(endType) {
                case "clear": m.EndState="cleared";m.EndAction="none";break;
                case "fail":m.EndState="failed";m.EndAction="none";break;
                case "quit":m.EndState="incomplete";m.EndAction="quit";reason="quit";break;
                case "restart":m.EndState="incomplete";m.EndAction="restart";reason="restarted";break;
                case "preflight_rejected":m.EndState="incomplete";m.EndAction="none";reason="preflight_rejected";break;
                default:m.EndType="unknown";m.EndState="unknown";m.EndAction="unknown";reason="unknown";break;
            }
            if(replayGzip!=null && replayGzip.Length>16*1024*1024) replayGzip=null;
            if(reason==null) {
                if(!m.SubmissionEligibility.AllowedAtStart || !m.SubmissionEligibility.RemainedAllowed) reason="submission_disabled";
                else if(replayGzip==null) reason="replay_unavailable";
            }
            if((endType=="clear" || endType=="fail") && replayGzip==null) m.Diagnostics.ReplayGenerationFailed=true;
            m.ScoreValidity.ValidForRanking=reason==null;m.ScoreValidity.InvalidReason=reason;m.ScoreValidity.RestartDetected=endType=="restart";m.ScoreValidity.PlayInstanceCount=context.Started || observedPlayCount>0 || context.GameplayGeneration>0?1:0;
            if(endType=="restart") m.ScoreValidity.PlayInstanceCount=1;
            return new ResultSnapshot {Metadata=m,ReplayGzip=replayGzip==null?null:(byte[])replayGzip.Clone()};
        }
        private static double? FiniteOrNull(double? value) { return value.HasValue && (double.IsNaN(value.Value)||double.IsInfinity(value.Value))?null:value; }
    }
}

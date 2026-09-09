using System;
using System.Linq;
using JBSLViewer.Qualifier.Core.Contracts;
namespace JBSLViewer.Qualifier.Core {
    public sealed class QualifierEligibilityEvaluator {
        public bool Evaluate(SelectionSnapshot s,DateTimeOffset now) {
            try {
                if(s==null || !s.IsSolo || !s.LeaderboardFresh || s.LeagueId<=0 || s.Map==null || string.IsNullOrWhiteSpace(s.CurrentSid) || !s.LocalSongDurationSeconds.HasValue || !StrictJson.FinitePositive(s.LocalSongDurationSeconds.Value)) return false;
                var b=s.Leaderboard; var q=b?.Qualifier;
                if(b==null || b.LeagueId!=s.LeagueId || q==null || !q.Enabled || q.SubmissionMethod!="jbsl_qualifier_v1" || !b.IsLive || !b.IsOpen || string.IsNullOrWhiteSpace(q.Revision) || (q.StartsAt.HasValue && now<q.StartsAt.Value)) return false;
                var end=q.EndsAt??b.End;
                if(end==default(DateTimeOffset) || now>end.AddSeconds(-s.LocalSongDurationSeconds.Value)) return false;
                if(b.Maps==null || b.Participants==null || b.Participants.Count(p=>p.Sid==s.CurrentSid)!=1 || b.Participants.GroupBy(p=>p.Sid).Any(g=>g.Count()>1) || b.Maps.GroupBy(m=>m.Key).Any(g=>g.Count()>1)) return false;
                var maps=b.Maps.Where(m=>m.Key.Equals(s.Map)).ToList(); return maps.Count==1 && maps[0].AttemptLimit>=1 && maps[0].AttemptLimit<=100;
            } catch { return false; }
        }
    }
}

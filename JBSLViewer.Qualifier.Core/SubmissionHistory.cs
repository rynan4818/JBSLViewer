using System.Collections.Generic;
using System.Linq;
using JBSLViewer.Qualifier.Core.Contracts;
namespace JBSLViewer.Qualifier.Core {
    public sealed class SubmissionHistory {
        private readonly object _sync=new object(); private readonly HashSet<string> _blockers=new HashSet<string>(); private bool _observedBlocked;private bool _allowedAtStart;
        public bool StartObserved { get; private set; }
        public void Observe(bool allowed,params string[] blockers) { lock(_sync) { if(!allowed) _observedBlocked=true; if(blockers!=null) foreach(var b in blockers) if(!string.IsNullOrWhiteSpace(b)) _blockers.Add(b); } }
        public void MarkStarted(bool allowed,params string[] blockers) { lock(_sync) { if(!StartObserved) { _allowedAtStart=allowed;StartObserved=true; } Observe(allowed,blockers); } }
        public SubmissionEligibility ToContract() { lock(_sync) return new SubmissionEligibility {AllowedAtStart=_allowedAtStart,RemainedAllowed=_allowedAtStart&&!_observedBlocked,Blockers=_blockers.OrderBy(x=>x).ToArray()}; }
    }
}

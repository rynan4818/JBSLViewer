using System.Collections.Generic;
namespace JBSLViewer.Qualifier.Core {
    public sealed class CompletedChallengeGuard {
        private readonly HashSet<string> _completed=new HashSet<string>();
        public bool TryComplete(string challengeId,long gameplayGeneration) { lock(_completed) return _completed.Add(challengeId+":"+gameplayGeneration); }
        public bool IsComplete(string challengeId,long gameplayGeneration) { lock(_completed) return _completed.Contains(challengeId+":"+gameplayGeneration); }
    }
}

using JBSLViewer.Qualifier.Core.Contracts;
namespace JBSLViewer.Qualifier.Core {
    public sealed class ReserveOperation {
        public GateToken Gate { get; internal set; }
        public string Key { get; internal set; }
        public ReserveRequest Request { get; internal set; }
        public ChallengeContext Context { get; internal set; }
        public bool TimedOut { get; internal set; }
        public bool Resolved { get; internal set; }
        public bool SuccessProcessed { get; internal set; }
        internal ScoreSession Session { get; set; }
    }
}

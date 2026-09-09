using JBSLViewer.Qualifier.Core;
using JBSLViewer.Qualifier.Core.Contracts;

namespace JBSLViewer.Qualifier
{
    public interface IQualifierGameplayHost
    {
        ChallengeContext ActiveChallenge { get; }
        string PlayerName { get; }
        string Platform { get; }
        string ClientVersion { get; }
        string Notice { get; }
        bool HideResultRestart { get; }
        void GameplayStarted(ChallengeContext context, long generation);
        // Must detach active context synchronously, before starting encoding or any await.
        void GameplayFinished(ChallengeContext context, long generation, ResultMetadata metadata, Core.Replay.Replay replay);
        void OrdinaryRestartDetected();
    }
}

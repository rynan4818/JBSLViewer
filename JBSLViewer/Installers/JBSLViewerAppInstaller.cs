using JBSLViewer.Models;
using Zenject;
using JBSLViewer.Qualifier;

namespace JBSLViewer.Installers
{
    public class JBSLViewerAppInstaller : Installer
    {
        public override void InstallBindings()
        {
            Container.BindInterfacesAndSelfTo<QualifierDispatcher>().AsSingle().NonLazy();
            Container.BindExecutionOrder<QualifierDispatcher>(-1000);
            Container.BindInterfacesAndSelfTo<PlayerIdentityService>().AsSingle().NonLazy();
            Container.BindInterfacesAndSelfTo<SubmissionEligibilityTracker>().AsSingle().NonLazy();
            Container.BindInterfacesAndSelfTo<QualifierRuntime>().AsSingle().NonLazy();
            this.Container.BindInterfacesAndSelfTo<SaveData>().AsSingle().NonLazy();
            this.Container.BindInterfacesAndSelfTo<ActiveLeague>().AsSingle().NonLazy();
            this.Container.BindInterfacesAndSelfTo<Leaderboard>().AsSingle().NonLazy();
            this.Container.BindInterfacesAndSelfTo<LatestUpdate>().AsSingle().NonLazy();
            this.Container.BindInterfacesAndSelfTo<LeaderboardInfo>().AsSingle().NonLazy();
            this.Container.BindInterfacesAndSelfTo<VirtualLeagueService>().AsSingle().NonLazy();
        }
    }
}

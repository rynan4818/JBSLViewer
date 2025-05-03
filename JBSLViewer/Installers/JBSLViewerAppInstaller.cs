using JBSLViewer.Models;
using Zenject;

namespace JBSLViewer.Installers
{
    public class JBSLViewerAppInstaller : Installer
    {
        public override void InstallBindings()
        {
            this.Container.BindInterfacesAndSelfTo<ActiveLeague>().AsSingle().NonLazy();
            this.Container.BindInterfacesAndSelfTo<Leaderboard>().AsSingle().NonLazy();
            this.Container.BindInterfacesAndSelfTo<LatestUpdate>().AsSingle().NonLazy();
        }
    }
}

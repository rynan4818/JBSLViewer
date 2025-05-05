using JBSLViewer.Models;
using JBSLViewer.Registerers;
using JBSLViewer.Views;
using Zenject;

namespace JBSLViewer.Installers
{
    public class JBSLViewerMenuInstaller : MonoInstaller
    {
        public override void InstallBindings()
        {
            this.Container.BindInterfacesAndSelfTo<LeaderboardPanelViewController>().FromNewComponentAsViewController().AsSingle().NonLazy();
            this.Container.BindInterfacesAndSelfTo<LeaderboardMainViewController>().FromNewComponentAsViewController().AsSingle().NonLazy();
            this.Container.BindInterfacesAndSelfTo<LeaderboardRegisterer>().AsSingle();
            this.Container.BindInterfacesAndSelfTo<UIManager>().AsSingle();
        }
    }
}

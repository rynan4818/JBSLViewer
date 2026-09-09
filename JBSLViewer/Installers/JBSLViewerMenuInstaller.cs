using JBSLViewer.Models;
using JBSLViewer.Registerers;
using JBSLViewer.Views;
using Zenject;
using JBSLViewer.Qualifier;

namespace JBSLViewer.Installers
{
    public class JBSLViewerMenuInstaller : MonoInstaller
    {
        public override void InstallBindings()
        {
            this.Container.BindInterfacesAndSelfTo<LeaderboardPanelViewController>().FromNewComponentAsViewController().AsSingle().NonLazy();
            this.Container.BindInterfacesAndSelfTo<LeaderboardMainViewController>().FromNewComponentAsViewController().AsSingle().NonLazy();
            this.Container.BindInterfacesAndSelfTo<JBSLViewerSettingView>().AsSingle().NonLazy();
            this.Container.BindInterfacesAndSelfTo<LeaderboardRegisterer>().AsSingle();
            this.Container.BindInterfacesAndSelfTo<VirtualLeagueScoreUploadWatcher>().FromNewComponentOnNewGameObject().AsSingle().NonLazy();
            this.Container.BindInterfacesAndSelfTo<UIManager>().AsSingle();
            Container.BindInterfacesAndSelfTo<StandardPlayAdapter>().AsSingle().NonLazy();
            Container.BindInterfacesAndSelfTo<QualifierMenuController>().AsSingle().NonLazy();
            Container.BindInterfacesAndSelfTo<QualifierRestartUiController>().AsSingle().NonLazy();
        }
    }
}

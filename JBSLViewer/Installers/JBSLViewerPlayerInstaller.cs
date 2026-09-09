using JBSLViewer.Qualifier;
using Zenject;

namespace JBSLViewer.Installers
{
    public class JBSLViewerPlayerInstaller : Installer
    {
        public override void InstallBindings()
        {
            Container.BindInterfacesAndSelfTo<QualifierReplayRecorder>().AsSingle().NonLazy();
            Container.BindInterfacesAndSelfTo<QualifierGameplayObserver>().AsSingle().NonLazy();
        }
    }
}

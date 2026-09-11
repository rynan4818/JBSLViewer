/*
Portions copied/adapted from TournamentAssistant.
Source: https://github.com/MatrikMoon/TournamentAssistant?tab=MIT-1-ov-file
Original: TournamentAssistant/Plugin.cs (CreateMenuButton, MenuButtonPressed, disposal)
Revision: ab4021a49f889bc36059efe3d8a2431097f1ffa5

MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
*/
using System;
using System.Linq;
using BeatSaberMarkupLanguage;
using BeatSaberMarkupLanguage.MenuButtons;
using HMUI;
using JBSLViewer.Qualifier.Core.Contracts;
using UnityEngine;
using Zenject;

namespace JBSLViewer.Qualifier.UI
{
    public sealed class QualifierMenuEntry : IInitializable, IDisposable
    {
        private readonly DiContainer _container;
        private MainFlowCoordinator _main;
        private readonly SoloFreePlayFlowCoordinator _solo;
        private readonly QualifierRuntime _runtime;
        private readonly QualifierRoomState _room;
        private QualifierFlowCoordinator _flow;
        private FlowCoordinator _parent;
        private MenuButton _button;
        private bool _disposed, _changing;
        public static QualifierMenuEntry Instance { get; private set; }
        public bool IsOpen => _flow != null && _room.IsOpen;
        public bool OwnsSelection => IsOpen;
        public QualifierBeatmap SelectedBeatmap => IsOpen ? _flow.SelectedBeatmap : null;
        public bool SelectionReady => IsOpen && !_room.ShowingResults && _flow.HasSelectedSong && _flow.SelectedBeatmap.IsReady;
        public bool CanReceiveDirectResult => IsOpen && _flow.isActivated && !_changing
            && _flow.topViewController?.isInTransition != true && MainFlow?.YoungestChildFlowCoordinatorOrSelf() == _flow;
        public int LeagueId => _room.LeagueId;
        public MainFlowCoordinator MainFlow => _main ?? (_main = Resources.FindObjectsOfTypeAll<MainFlowCoordinator>().FirstOrDefault(flow => flow.gameObject.scene.IsValid()));
        public bool CanOpen
        {
            get
            {
                if (_disposed || _changing || IsOpen || _room.LaunchPending || _runtime.SelectionLocked || _runtime.SceneTransitioning || MainFlow == null) return false;
                var parent = _main.YoungestChildFlowCoordinatorOrSelf();
                return (parent == _main || parent == _solo) && parent.topViewController?.isInTransition != true;
            }
        }

        public QualifierMenuEntry(DiContainer container, [InjectOptional] MainFlowCoordinator main, SoloFreePlayFlowCoordinator solo,
            QualifierRuntime runtime, QualifierRoomState room)
        { _container = container; _main = main; _solo = solo; _runtime = runtime; _room = room; }
        public void Initialize()
        {
            if (MainFlow == null) { Plugin.Log.Error("Challenge menu could not find the main menu flow."); return; }
            Instance = this;
            _button = new MenuButton("JBSL CHALLENGE", () => Open());
            MenuButtons.instance.RegisterButton(_button);
        }
        public void Open(int leagueId = 0, MapKey map = null)
        {
            if (!CanOpen) return;
            var parent = _main.YoungestChildFlowCoordinatorOrSelf();
            if (parent != _main && parent != _solo) return;
            _room.Open(leagueId, map);
            Present(parent);
        }
        private void Present(FlowCoordinator parent)
        {
            _changing = true;
            try
            {
                _parent = parent;
                _flow = BeatSaberUI.CreateFlowCoordinator<QualifierFlowCoordinator>();
                _container.Inject(_flow);
                _flow.ExitRequested += Close;
                parent.PresentFlowCoordinator(_flow, immediately: true);
            }
            catch
            {
                _room.Close();
                if (_flow != null) UnityEngine.Object.Destroy(_flow.gameObject);
                _flow = null;
                throw;
            }
            finally { _changing = false; }
        }
        private void Dismiss()
        {
            if (_flow == null) return;
            var flow = _flow;
            flow.PrepareForDismiss();
            if (_parent != null && _parent.childFlowCoordinator == flow)
                _parent.DismissFlowCoordinator(flow, immediately: true);
            _flow = null; _parent = null;
            UnityEngine.Object.Destroy(flow.gameObject);
        }
        private void Close()
        {
            if (_runtime.SelectionLocked || _room.LaunchPending || _changing) return;
            _room.Close();
            Dismiss();
            QualifierMenuController.Instance?.SelectionUpdated();
        }
        public bool BeginDirectLaunch(bool practice)
        {
            // Keep this flow and its parent in place, as TA does. The standard
            // scene transition hides/restores the menu without a Solo detour.
            return SelectionReady && _room.BeginLaunch(practice);
        }
        public void ApplyLock() => _flow?.ApplyLock();
        public void ShowDirectResult(QualifierDirectPlayResult result)
        {
            if (_disposed || !IsOpen) return;
            try { _flow.ShowDirectResult(result); }
            catch (Exception ex)
            {
                Plugin.Log.Error("Challenge result screen failed: " + ex);
                _flow.RecoverAfterResultFailure();
            }
        }
        public void Dispose()
        {
            _disposed = true;
            if (MenuButtons.instance != null) MenuButtons.instance.UnregisterButton(_button);
            if (_flow != null) UnityEngine.Object.Destroy(_flow.gameObject);
            _flow = null;
            if (Instance == this) Instance = null;
        }
    }
}

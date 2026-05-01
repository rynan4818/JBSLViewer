using System;
using BeatSaberMarkupLanguage.Attributes;
using BeatSaberMarkupLanguage.Settings;
using JBSLViewer.Configuration;
using JBSLViewer.Models;
using Zenject;

namespace JBSLViewer.Views
{
    public class JBSLViewerSettingView : IInitializable, IDisposable
    {
        private const string ButtonName = "JBSLViewer";
        private readonly VirtualLeagueService _virtualLeagueService;
        private bool _disposedValue;

        public JBSLViewerSettingView(VirtualLeagueService virtualLeagueService)
        {
            this._virtualLeagueService = virtualLeagueService;
        }

        public string ResourceName => string.Join(".", this.GetType().Namespace, this.GetType().Name);

        public void Initialize()
        {
            BSMLSettings.Instance.AddSettingsMenu(ButtonName, this.ResourceName, this);
        }

        public void Dispose()
        {
            if (this._disposedValue)
                return;

            BSMLSettings.Instance?.RemoveSettingsMenu(ButtonName);
            this._disposedValue = true;
        }

        [UIValue("UseScoreSaberMaxScoreForVirtualLeague")]
        public bool UseScoreSaberMaxScoreForVirtualLeague
        {
            get => PluginConfig.Instance.useScoreSaberMaxScoreForVirtualLeague;
            set
            {
                if (PluginConfig.Instance.useScoreSaberMaxScoreForVirtualLeague == value)
                    return;

                PluginConfig.Instance.useScoreSaberMaxScoreForVirtualLeague = value;
                this._virtualLeagueService.OnAccuracyModeChanged();
            }
        }
    }
}

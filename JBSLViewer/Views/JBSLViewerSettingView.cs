using System;
using BeatSaberMarkupLanguage.Attributes;
using BeatSaberMarkupLanguage.Settings;
using JBSLViewer.Configuration;
using JBSLViewer.Models;
using Zenject;
using System.ComponentModel;
using JBSLViewer.Qualifier;
using HMUI;

namespace JBSLViewer.Views
{
    public class JBSLViewerSettingView : IInitializable, IDisposable, INotifyPropertyChanged
    {
        private const string ButtonName = "JBSLViewer";
        private readonly VirtualLeagueService _virtualLeagueService;
        private bool _disposedValue;
        private readonly QualifierRuntime _qualifier;
        private string _outboxStatus;
        private bool _busy;
        public event PropertyChangedEventHandler PropertyChanged;
        [UIComponent("ClearResultsModal")] private readonly ModalView _clearModal;

        public JBSLViewerSettingView(VirtualLeagueService virtualLeagueService, QualifierRuntime qualifier)
        {
            this._virtualLeagueService = virtualLeagueService;
            _qualifier = qualifier;
        }

        public string ResourceName => string.Join(".", this.GetType().Namespace, this.GetType().Name);

        public void Initialize()
        {
            BSMLSettings.Instance.AddSettingsMenu(ButtonName, this.ResourceName, this);
            _qualifier.StateChanged += RefreshQualifier;
            RefreshQualifier();
        }

        public void Dispose()
        {
            if (this._disposedValue)
                return;

            BSMLSettings.Instance?.RemoveSettingsMenu(ButtonName);
            _qualifier.StateChanged -= RefreshQualifier;
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

        [UIValue("ScoreServerUrl")]
        public string ScoreServerUrl
        {
            get => PluginConfig.Instance.scoreServerBaseUrl;
            set { PluginConfig.Instance.scoreServerBaseUrl = value?.Trim() ?? ""; PluginConfig.NotifyQualifierSettingsChanged(); }
        }
        [UIValue("AllowDevelopmentHttp")]
        public bool AllowDevelopmentHttp
        {
            get => PluginConfig.Instance.allowDevelopmentHttp;
            set { PluginConfig.Instance.allowDevelopmentHttp = value; PluginConfig.NotifyQualifierSettingsChanged(); }
        }
        [UIValue("OutboxStatus")] public string OutboxStatus => _outboxStatus;
        [UIValue("RetryEnabled")] public bool RetryEnabled => !_busy;
        [UIValue("ClearEnabled")] public bool ClearEnabled => !_busy && _qualifier.CanForceClear;
        private void RefreshQualifier()
        {
            _outboxStatus = (_qualifier.ConfigurationMessage == null ? "" : _qualifier.ConfigurationMessage + "\n")
                + _qualifier.DescribeOutbox();
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(OutboxStatus)));
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(RetryEnabled)));
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(ClearEnabled)));
        }
        [UIAction("RetryQualifier")]
        private async void RetryQualifier()
        {
            if (_busy) return;
            _busy = true; RefreshQualifier();
            try { await _qualifier.RetryManuallyAsync(); }
            catch (Exception ex) { Plugin.Log.Warn("Qualifier manual retry failed: " + ex.GetType().Name); }
            finally { _busy = false; RefreshQualifier(); }
        }
        [UIAction("AskClearQualifier")]
        private void AskClearQualifier() { if (ClearEnabled) _clearModal.Show(true, true); }
        [UIAction("CancelClearQualifier")]
        private void CancelClearQualifier() => _clearModal.Hide(true);
        [UIAction("ClearQualifier")]
        private async void ClearQualifier()
        {
            _clearModal.Hide(true);
            if (!ClearEnabled) return;
            _busy = true; RefreshQualifier();
            try { await _qualifier.ForceClearAsync(); }
            catch (Exception ex) { Plugin.Log.Warn("Qualifier clear failed: " + ex.GetType().Name); }
            finally { _busy = false; RefreshQualifier(); }
        }
    }
}

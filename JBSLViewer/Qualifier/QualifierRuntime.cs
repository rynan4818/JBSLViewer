using System;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using JBSLViewer.Configuration;
using JBSLViewer.Qualifier.Core;
using JBSLViewer.Qualifier.Core.Contracts;
using JBSLViewer.Qualifier.Core.Outbox;
using Zenject;

namespace JBSLViewer.Qualifier
{
    // App scope keeps reservations and results alive across menu/gameplay scenes.
    public sealed class QualifierRuntime : IInitializable, ITickable, IDisposable, IQualifierHost, IQualifierGameplayHost
    {
        private readonly QualifierDispatcher _dispatcher;
        private readonly PlayerIdentityService _identity;
        private readonly SubmissionEligibilityTracker _submission;
        private readonly QualifierRoomState _room;
        private readonly ScoreManagerApiClient _api = new ScoreManagerApiClient();
        private readonly AuthenticationSession _auth;
        private readonly CancellationTokenSource _lifetime = new CancellationTokenSource();
        private QualifierOutbox _outbox;
        private QualifierChallengeCoordinator _coordinator;
        private QualifierMenuController _menu;
        [InjectOptional] private GameScenesManager _scenes;
        private bool _sceneTransitioning;
        internal bool SceneTransitioning => _sceneTransitioning;
        private SelectionSnapshot _selection = new SelectionSnapshot();
        private Task _refresh, _retry;
        private DateTimeOffset _nextTick;
        private string _configurationError, _initializationError, _notice;
        private bool _disposed, _hideResultRestart;
        private SubmissionObservation _eligibility = new SubmissionObservation { Allowed = false, Blockers = new[] { "initializing" } };
        public static QualifierRuntime Instance { get; private set; }
        public event Action SelectionChanged;
        public event Action StateChanged;
        public bool SelectionLocked { get; private set; }
        public ChallengeContext ActiveChallenge => _coordinator?.ActiveChallenge;
        public string PlayerName => _identity.PlayerName;
        public string Platform => _identity.Platform;
        public string ClientVersion => "JBSLViewer/" + typeof(Plugin).Assembly.GetName().Version;
        public bool HideResultRestart => _hideResultRestart;
        public bool CanForceClear => _coordinator?.HasUnresolved == true && ActiveChallenge == null && _coordinator.PendingReserve == null;
        public QualifierViewState ViewState => _coordinator?.ViewState ?? new QualifierViewState();
        public string ConfigurationMessage => _initializationError ?? _configurationError;
        public string Notice => _notice;
        public string OutboxDirectory => Path.Combine(IPA.Utilities.UnityGame.UserDataPath, "JBSLViewer", "QualifierOutbox");

        public QualifierRuntime(QualifierDispatcher dispatcher, PlayerIdentityService identity, SubmissionEligibilityTracker submission, QualifierRoomState room)
        { _dispatcher = dispatcher; _identity = identity; _submission = submission; _room = room; _auth = new AuthenticationSession(_api, identity); }
        internal void StandardGameplayStarted() => _room.GameplayStarted();
        internal void StandardGameplayFinished() => _room.GameplayFinished();
        public void Initialize()
        {
            Instance = this;
            _identity.Changed += IdentityChanged;
            _submission.StateChanged += SubmissionChanged;
            PluginConfig.QualifierSettingsChanged += ConfigurationChanged;
            Plugin.OnPluginExit += Exiting;
            if (_scenes != null)
            {
                _scenes.transitionDidStartEvent += SceneTransitionStarted;
                _scenes.transitionDidFinishEvent += SceneTransitionFinished;
            }
            SubmissionChanged(); ApplyConfiguration();
            _ = InitializeOutboxAsync();
        }
        private async Task InitializeOutboxAsync()
        {
            try
            {
                var directory = OutboxDirectory;
                var outbox = await Task.Run(() => new QualifierOutbox(new OutboxStore(directory), _api, _auth));
                if (_disposed) return;
                _outbox = outbox;
                _coordinator = new QualifierChallengeCoordinator(_api, _auth, _outbox, this) { ClientVersion = ClientVersion, GameVersion = UnityEngine.Application.version };
                _coordinator.StateChanged += NotifyState;
                ApplyConfiguration(); _coordinator.Reevaluate();
                _retry = RetryAutomaticallyAsync();
            }
            catch (Exception ex)
            {
                _initializationError = "Outbox could not be loaded. Preserve its files and check the log.";
                Plugin.Log.Error("Qualifier outbox initialization failed: " + ex.GetType().Name); NotifyState();
            }
        }
        private void IdentityChanged() { _auth.RefreshIdentity(); _menu?.SelectionUpdated(); NotifyState(); }
        private void SceneTransitionStarted(float duration)
        { _sceneTransitioning = true; _menu?.SelectionUpdated(); }
        private void SceneTransitionFinished(ScenesTransitionSetupDataSO setup, DiContainer container)
        { _sceneTransitioning = false; _menu?.SelectionUpdated(); }
        private void SubmissionChanged() { _eligibility = _submission.ReadCurrent(); _coordinator?.Reevaluate(); }
        private void ConfigurationChanged() => _dispatcher.Post(ApplyConfiguration);
        private void ApplyConfiguration()
        {
            var config = PluginConfig.Instance;
            _api.RequestTimeout = TimeSpan.FromSeconds(Math.Max(5, Math.Min(300, config.qualifierRequestTimeoutSeconds)));
            if (_coordinator != null) _coordinator.ReserveUiTimeout = _api.RequestTimeout;
            try { _auth.Configure(config.scoreServerBaseUrl, config.allowDevelopmentHttp); _configurationError = null; }
            catch (ArgumentException)
            {
                _auth.ClearConfiguration();
                _configurationError = string.IsNullOrWhiteSpace(config.scoreServerBaseUrl)
                    ? "Set the score server URL in JBSLViewer settings."
                    : "Invalid score server URL. HTTPS required (development HTTP: localhost/127.0.0.1 only).";
            }
            NotifyState();
        }
        public void Tick()
        {
            if (_coordinator == null || _disposed || DateTimeOffset.UtcNow < _nextTick) return;
            _nextTick = DateTimeOffset.UtcNow.AddSeconds(1);
            _menu?.SelectionUpdated();
            _coordinator.Reevaluate();
            if (_refresh == null || _refresh.IsCompleted) _refresh = RefreshAsync();
            if (_retry == null || _retry.IsCompleted) _retry = RetryAutomaticallyAsync();
        }
        private async Task RefreshAsync()
        {
            try { await _coordinator.RefreshAsync(); }
            catch (Exception ex) { Plugin.Log.Warn("Qualifier status refresh failed: " + ex.GetType().Name); }
        }
        private async Task RetryAutomaticallyAsync()
        {
            try { await _outbox.RetryAsync(false, _lifetime.Token); }
            catch (OperationCanceledException) { }
            catch (Exception ex) { Plugin.Log.Warn("Qualifier retry failed: " + ex.GetType().Name); }
        }
        private void NotifyState() => _dispatcher.Post(() => StateChanged?.Invoke());
        internal void AttachMenu(QualifierMenuController menu) { _menu = menu; }
        internal void DetachMenu(QualifierMenuController menu)
        {
            if (!ReferenceEquals(_menu, menu)) return;
            _menu = null;
            UpdateSelection(new SelectionSnapshot { CurrentSid = _identity.CurrentSid, SelectionGeneration = _selection.SelectionGeneration + 1 });
        }
        internal void UpdateSelection(SelectionSnapshot snapshot) { _selection = snapshot; SelectionChanged?.Invoke(); }
        public SelectionSnapshot CaptureSelection() => _selection;
        public bool IsSubmissionAllowed(out string[] blockers)
        {
            if (!Plugin.QualifierHooksReady) { blockers = new[] { "qualifier_hooks_unavailable" }; return false; }
            var current = _eligibility; blockers = current.Blockers; return current.Allowed;
        }
        public void SetSelectionLocked(bool locked)
        {
            SelectionLocked = locked;
            _dispatcher.Post(() => { _menu?.ApplyLock(); StateChanged?.Invoke(); });
        }
        internal bool MenuCanStart(ChallengeContext context) => _menu?.CanStart(context) == true;
        public Task<bool> StartStandardPlayAsync(ChallengeContext context)
        {
            return _dispatcher.RunAsync(async () =>
            {
                _notice = null; _hideResultRestart = false;
                return _menu != null && await _menu.StartAsync(context);
            });
        }
        public bool BeginConfirmation() => _coordinator?.BeginConfirmation() == true;
        public void CancelConfirmation() => _coordinator?.CancelConfirmation();
        public Task ConfirmAsync() => _coordinator?.ConfirmAsync() ?? Task.CompletedTask;
        public void GameplayStarted(ChallengeContext context, long generation)
        {
            StandardPlayAdapter.Pending?.Arrived(context);
            _ = _coordinator.MarkStartedAsync(context, generation);
        }
        public void GameplayFinished(ChallengeContext context, long generation, ResultMetadata metadata, Core.Replay.Replay replay)
        {
            // Must happen before any asynchronous encoding, saving or scene replacement.
            if (_coordinator?.DetachForFinalization(context, generation) != true) return;
            StandardPlayAdapter.Pending?.Arrived(context);
            _hideResultRestart = metadata.EndType == "clear" || metadata.EndType == "fail";
            _ = FinalizeAsync(context, metadata, replay);
        }
        private async Task FinalizeAsync(ChallengeContext context, ResultMetadata metadata, Core.Replay.Replay replay)
        {
            byte[] gzip = null;
            if (replay != null)
            {
                try
                {
                    gzip = await Task.Run(() =>
                    {
                        using (var memory = new MemoryStream())
                        {
                            using (var stream = new GZipStream(memory, CompressionLevel.Optimal, true))
                            using (var writer = new BinaryWriter(stream)) Core.Replay.ReplayEncoder.Encode(replay, writer);
                            return memory.ToArray();
                        }
                    });
                }
                catch (Exception ex)
                {
                    metadata.Diagnostics.ReplayGenerationFailed = true;
                    Plugin.Log.Warn("Qualifier replay encoding failed: " + ex.GetType().Name);
                }
            }
            try { await _coordinator.CompleteAsync(context, QualifierResultFactory.Create(context, metadata.EndType, metadata, gzip)); }
            catch (Exception ex) { Plugin.Log.Error("Qualifier result finalization failed: " + ex.GetType().Name); }
        }
        public void OrdinaryRestartDetected()
        {
            _notice = "Restart made this a normal play: its score is not sent to JBSL. The original challenge result is processed separately.";
            _hideResultRestart = false; NotifyState();
        }
        internal void OrdinaryPlayRequested() { _notice = null; _hideResultRestart = false; NotifyState(); }
        public async Task RetryManuallyAsync()
        {
            if (_outbox == null) return;
            await _identity.RefreshAsync(); _auth.RefreshIdentity();
            if (!_outbox.HasUnresolved && _auth.Endpoint != null
                && new QualifierEligibilityEvaluator().Evaluate(CaptureSelection(), DateTimeOffset.UtcNow)) await _auth.EnsureAsync(true);
            await _outbox.RetryAsync(true, _lifetime.Token);
            if (_coordinator != null) await _coordinator.RefreshAsync(true);
        }
        public async Task ForceClearAsync()
        { if (CanForceClear) { await _coordinator.ForceClearResultsAsync(); _coordinator.Reevaluate(); } }
        public string DescribeOutbox()
        {
            if (_initializationError != null) return _initializationError;
            if (_outbox == null) return "Loading saved results...";
            var entries = _outbox.GetSummaries();
            if (entries.Count == 0) return "No unresolved results.";
            return "Unresolved: " + entries.Count(e => e.State != "sent") + (entries.Count > 20 ? " (showing 20 results)" : "") + "\n"
                + string.Join("\n\n", entries.OrderBy(e => e.State == "sent" ? 1 : 0).ThenByDescending(e => e.Response?.ReceivedAt).Take(20)
                .Select(e => e.State + (e.BlockedReason == null ? "" : " / " + e.BlockedReason)
                + (e.OwnerMismatch ? " / owner_mismatch" : "")
                + "\n" + e.ScoreServerBaseUrl + "\n" + e.ChallengeId
                + (e.Response == null ? "" : "\n" + (e.Response.ValidForRanking ? "Accepted for ranking" : "Invalid: " + e.Response.InvalidReason))
                + (e.ErrorCode == null ? "" : "\n" + e.ErrorCode)
                + (e.HttpStatus.HasValue ? " (HTTP " + e.HttpStatus.Value + ")" : "")
                + (e.RequestId == null ? "" : "\nRequest: " + e.RequestId)));
        }
        private void Exiting()
        { QualifierGameplayObserver.FlushUnexpectedExit(); _coordinator?.Dispose(); _lifetime.Cancel(); }
        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            _identity.Changed -= IdentityChanged; _submission.StateChanged -= SubmissionChanged;
            PluginConfig.QualifierSettingsChanged -= ConfigurationChanged; Plugin.OnPluginExit -= Exiting;
            if (_scenes != null)
            {
                _scenes.transitionDidStartEvent -= SceneTransitionStarted;
                _scenes.transitionDidFinishEvent -= SceneTransitionFinished;
            }
            _coordinator?.Dispose(); _lifetime.Cancel(); _auth.Dispose();
            if (Instance == this) Instance = null;
        }
    }
}

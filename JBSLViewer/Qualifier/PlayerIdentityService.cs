// Platform ticket flow follows BeatLeader Authentication.cs (MIT):
// https://github.com/BeatLeader/beatleader-mod/blob/1291supportx/LICENSE
// Copyright (c) 2023 BeatLeader. See THIRD-PARTY-NOTICES.txt.
using System;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using IPA.Utilities;
using JBSLViewer.Qualifier.Core;
using UnityEngine;
using Zenject;

namespace JBSLViewer.Qualifier
{
    public sealed class PlayerIdentityService : IPlatformTicketProvider, IInitializable, ITickable
    {
        private readonly QualifierDispatcher _dispatcher;
        [InjectOptional] private IPlatformUserModel _platformUserModel;
        private UserInfo _user;
        private bool _refreshing;
        private float _nextPoll;
        public string CurrentSid => _user?.platformUserId;
        public string PlayerName => _user?.userName ?? "";
        public string Platform => _user?.platform.ToString().ToLowerInvariant() ?? "";
        public event Action Changed;

        public PlayerIdentityService(QualifierDispatcher dispatcher) { _dispatcher = dispatcher; }
        public void Initialize() { _ = RefreshAsync(); }
        public void Tick()
        {
            if (Time.realtimeSinceStartup < _nextPoll) return;
            _nextPoll = Time.realtimeSinceStartup + 5;
            _ = RefreshAsync();
        }
        public Task<bool> RefreshAsync() => _dispatcher.RunAsync(RefreshOnMainAsync);
        private async Task<bool> RefreshOnMainAsync()
        {
            if (_refreshing) return _user != null;
            _refreshing = true;
            try
            {
                if (_platformUserModel == null)
                    _platformUserModel = Resources.FindObjectsOfTypeAll<PlatformLeaderboardsModel>()
                        .Select(x => x.GetField<IPlatformUserModel, PlatformLeaderboardsModel>("_platformUserModel"))
                        .LastOrDefault(x => x != null);
                var user = _platformUserModel == null ? null : await _platformUserModel.GetUserInfo();
                SetUser(user);
                return user != null;
            }
            catch (Exception) { SetUser(null); return false; }
            finally { _refreshing = false; }
        }
        private void SetUser(UserInfo user)
        {
            var changed = _user?.platformUserId != user?.platformUserId || _user?.platform != user?.platform;
            _user = user;
            if (changed) Changed?.Invoke();
        }
        public Task<PlatformTicket> GetTicketAsync(CancellationToken cancellationToken)
        {
            return _dispatcher.RunAsync(async () =>
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (!await RefreshOnMainAsync() || _user == null) throw new InvalidOperationException("Platform identity unavailable.");
                var user = _user;
                if (user.platform == UserInfo.Platform.Steam)
                {
                    var token = await new PlatformAuthenticationTokenProvider(_platformUserModel, user).GetAuthenticationToken();
                    cancellationToken.ThrowIfCancellationRequested();
                    return new PlatformTicket { Provider = "steamTicket", Ticket = token.sessionToken };
                }
                if (user.platform == UserInfo.Platform.Oculus)
                {
                    var completion = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
                    using (cancellationToken.Register(() => completion.TrySetCanceled()))
                    {
                        Oculus.Platform.Users.GetAccessToken().OnComplete(message =>
                        {
                            if (message.IsError) completion.TrySetException(new InvalidOperationException("Oculus ticket unavailable."));
                            else completion.TrySetResult(message.Data);
                        });
                        return new PlatformTicket { Provider = "oculusTicket", Ticket = await completion.Task };
                    }
                }
                throw new InvalidOperationException("Unsupported platform.");
            });
        }
    }
}

using System.Threading.Tasks;
using JBSLViewer.Models;
using LeaderboardCore.Interfaces;
using UnityEngine;
using Zenject;

namespace JBSLViewer.Views
{
    public class VirtualLeagueScoreUploadWatcher : MonoBehaviour, INotifyScoreUpload
    {
        private VirtualLeagueService _virtualLeagueService;

        [Inject]
        public void Construct(VirtualLeagueService virtualLeagueService)
        {
            this._virtualLeagueService = virtualLeagueService;
        }

        public void OnScoreUploaded()
        {
            _ = this.HandleScoreUploadedAsync();
        }

        private async Task HandleScoreUploadedAsync()
        {
            if (this._virtualLeagueService == null)
                return;
            await this._virtualLeagueService.HandleScoreUploadedAsync();
        }
    }
}

using System;
using System.Threading;
using System.Threading.Tasks;
namespace JBSLViewer.Qualifier.Core {
    public interface IClock { DateTimeOffset UtcNow { get; } }
    public sealed class SystemClock : IClock { public DateTimeOffset UtcNow { get { return DateTimeOffset.UtcNow; } } }
    public sealed class PlatformTicket { public string Provider { get; set; } public string Ticket { get; set; } }
    public interface IPlatformTicketProvider { string CurrentSid { get; } Task<PlatformTicket> GetTicketAsync(CancellationToken cancellationToken); }
    public interface IQualifierHost {
        SelectionSnapshot CaptureSelection();
        bool IsSubmissionAllowed(out string[] blockers);
        void SetSelectionLocked(bool locked);
        Task<bool> StartStandardPlayAsync(ChallengeContext context);
        event Action SelectionChanged;
    }
}

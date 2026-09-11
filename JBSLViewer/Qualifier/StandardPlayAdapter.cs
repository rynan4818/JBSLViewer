using System;
using System.Reflection;
using System.Threading.Tasks;
using HarmonyLib;
using JBSLViewer.Qualifier.Core;
using Zenject;

namespace JBSLViewer.Qualifier
{
    public sealed class StandardPlayAdapter : IInitializable, IDisposable
    {
        private readonly SoloFreePlayFlowCoordinator _solo;
        private readonly SubmissionEligibilityTracker _submission;
        private readonly QualifierRuntime _runtime;
        private readonly QualifierDirectPlayController _direct;
        private TaskCompletionSource<bool> _arrival;
        private ChallengeContext _context;
        private static readonly MethodInfo PlayMethod = AccessTools.DeclaredMethod(
            typeof(SinglePlayerLevelSelectionFlowCoordinator), "ActionButtonWasPressed");
        internal static StandardPlayAdapter Pending { get; private set; }
        public bool Invoking { get; private set; }

        public StandardPlayAdapter(SoloFreePlayFlowCoordinator solo, SubmissionEligibilityTracker submission, QualifierRuntime runtime, QualifierDirectPlayController direct)
        { _solo = solo; _submission = submission; _runtime = runtime; _direct = direct; }
        public void Initialize() { _solo.didFinishEvent += FlowFinished; }
        public async Task<bool> StartAsync(ChallengeContext context)
        {
            if (context == null || _arrival != null || (!_direct.FromRoom && PlayMethod == null)) return false;
            _arrival = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            var arrivalTask = _arrival.Task;
            var completion = _arrival;
            _context = context;
            Pending = this;
            try
            {
                _submission.Track(context.Submission);
                if (_direct.FromRoom)
                {
                    var invoked = await _direct.StartChallengeAsync(context);
                    if (!ReferenceEquals(_context, context) || !ReferenceEquals(_arrival, completion)) return await arrivalTask;
                    if (!invoked) FailExplicitly();
                }
                else
                {
                    if (!_runtime.MenuCanStart(context)) { FailExplicitly(); return await arrivalTask; }
                    Invoking = true;
                    PlayMethod.Invoke(_solo, null);
                }
            }
            catch (Exception ex)
            {
                Plugin.Log.Warn("Challenge standard Play failed: " + ex);
                if (ReferenceEquals(_arrival, completion)) FailExplicitly();
            }
            finally { Invoking = false; }
            return await arrivalTask;
        }
        internal void Arrived(ChallengeContext context)
        {
            if (!ReferenceEquals(_context, context)) return;
            _arrival?.TrySetResult(true);
            _arrival = null;
            _context = null;
            if (Pending == this) Pending = null;
        }
        internal void FailExplicitly()
        {
            if (_context != null || _arrival != null)
                _direct.RejectPending(_context, "The challenge could not start. Check the result status before trying again.");
            if (_context != null) _submission.Detach(_context.Submission);
            _arrival?.TrySetResult(false);
            _arrival = null;
            _context = null;
            if (Pending == this) Pending = null;
        }
        internal void ReturnedWithoutArrival(ChallengeContext context)
        {
            if (context == null || !ReferenceEquals(_context, context)) return;
            // Let the coordinator seal a failed launch if no gameplay observer
            // ever acknowledged it. The room already owns the return/result UI.
            _submission.Detach(context.Submission);
            _arrival?.TrySetResult(false);
            _arrival = null;
            _context = null;
            if (Pending == this) Pending = null;
        }
        private void FlowFinished(SinglePlayerLevelSelectionFlowCoordinator flow) { FailExplicitly(); }
        public void Dispose()
        {
            if (_solo != null) _solo.didFinishEvent -= FlowFinished;
            // Menu unload is part of a normal level transition. It is not a failure.
        }
    }

    [HarmonyPatch(typeof(SinglePlayerLevelSelectionFlowCoordinator), nameof(SinglePlayerLevelSelectionFlowCoordinator.StartLevel))]
    internal static class QualifierStandardPlayFailurePatch
    {
        private static Exception Finalizer(Exception __exception)
        {
            if (__exception != null) StandardPlayAdapter.Pending?.FailExplicitly();
            return __exception;
        }
    }
}

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
        private TaskCompletionSource<bool> _arrival;
        private ChallengeContext _context;
        private static readonly MethodInfo PlayMethod = AccessTools.DeclaredMethod(
            typeof(SinglePlayerLevelSelectionFlowCoordinator), "ActionButtonWasPressed");
        internal static StandardPlayAdapter Pending { get; private set; }
        public bool Invoking { get; private set; }

        public StandardPlayAdapter(SoloFreePlayFlowCoordinator solo, SubmissionEligibilityTracker submission, QualifierRuntime runtime)
        { _solo = solo; _submission = submission; _runtime = runtime; }
        public void Initialize() { _solo.didFinishEvent += FlowFinished; }
        public Task<bool> StartAsync(ChallengeContext context)
        {
            if (_arrival != null || PlayMethod == null || !_runtime.MenuCanStart(context)) return Task.FromResult(false);
            _arrival = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            var arrivalTask = _arrival.Task;
            _context = context;
            Pending = this;
            _submission.Track(context.Submission);
            try
            {
                // Invoke the standard method once, with all patches on that method.
                // The NoFailCheck private button-event forwarding path is not invoked.
                Invoking = true;
                PlayMethod.Invoke(_solo, null);
            }
            catch (Exception) { FailExplicitly(); }
            finally { Invoking = false; }
            return arrivalTask;
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
            if (_context != null) _submission.Detach(_context.Submission);
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

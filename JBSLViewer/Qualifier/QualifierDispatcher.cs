using System;
using System.Collections.Concurrent;
using System.Threading;
using System.Threading.Tasks;
using Zenject;

namespace JBSLViewer.Qualifier
{
    // Platform APIs and all Unity objects are accessed on the Unity thread.
    public sealed class QualifierDispatcher : IInitializable, ITickable
    {
        private readonly ConcurrentQueue<Action> _queue = new ConcurrentQueue<Action>();
        private int _thread;
        public void Initialize() { _thread = Thread.CurrentThread.ManagedThreadId; }
        public void Post(Action action)
        {
            if (Thread.CurrentThread.ManagedThreadId == _thread) action();
            else _queue.Enqueue(action);
        }
        public Task<T> RunAsync<T>(Func<Task<T>> action)
        {
            var completion = new TaskCompletionSource<T>(TaskCreationOptions.RunContinuationsAsynchronously);
            Post(async () =>
            {
                try { completion.TrySetResult(await action()); }
                catch (OperationCanceledException) { completion.TrySetCanceled(); }
                catch (Exception ex) { completion.TrySetException(ex); }
            });
            return completion.Task;
        }
        public void Tick()
        {
            while (_queue.TryDequeue(out var action))
            {
                try { action(); }
                catch (Exception ex) { Plugin.Log.Error("Qualifier UI operation failed: " + ex.GetType().Name); }
            }
        }
    }
}

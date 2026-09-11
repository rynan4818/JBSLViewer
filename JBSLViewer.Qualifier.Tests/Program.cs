using System;
using System.Threading.Tasks;
namespace JBSLViewer.Qualifier.Tests {
    internal static class Program {
        internal static int Passed;
        internal static void Check(bool condition,string name) { if(!condition) throw new Exception("FAIL: "+name);Passed++;Console.WriteLine("PASS: "+name); }
        internal static void Reject(Action action,string name) { try { action(); } catch { Check(true,name);return; } throw new Exception("FAIL: accepted "+name); }
        private static int Main(string[] args) { try { Run(args).GetAwaiter().GetResult();Console.WriteLine("ALL PASSED: "+Passed);return 0; } catch(Exception ex) { Console.Error.WriteLine(ex);return 1; } }
        private static async Task Run(string[] args) { if(args.Length>0 && args[0]=="integration") await HttpContractScenarios.Run(args.Length>1?args[1]:"http://127.0.0.1:18081",args.Length>2?args[2]:"http://127.0.0.1:18080");else { await CoreScenarios.Run();await OutboxScenarios.Run();await AdditionalScenarios.Run();await LeaderboardCacheScenarios.Run();LeaderboardPagingScenarios.Run();ReplayScenarios.Run();await QualifierScreenScenarios.Run();await QualifierLaunchScenarios.Run();ReplayModeScenarios.Run(); } }
    }
}

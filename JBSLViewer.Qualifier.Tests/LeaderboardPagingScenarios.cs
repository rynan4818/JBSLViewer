using System;
using System.Collections.Generic;
using System.Linq;
using JBSLViewer.Models;

namespace JBSLViewer.Qualifier.Tests
{
    internal static class LeaderboardPagingScenarios
    {
        internal static void Run()
        {
            foreach (var count in new[] { 0, 1, 9, 10, 11, 20, 21 })
            {
                var page = new LeaderboardPageState();
                page.SetCount(count);
                Program.Check(page.Page == 0 && !page.CanPrevious && !page.Move(-1), $"{count} ranking rows: cannot move above the first page");
                var shown = new List<int>();
                var data = Enumerable.Range(1, count).ToList();
                var forwardStarts = new List<int>();
                do
                {
                    forwardStarts.Add(page.Offset);
                    var visible = data.Skip(page.Offset).Take(LeaderboardPageState.PageSize).ToList();
                    if (visible.Count > 10) throw new Exception("Page exceeds the original ten-record limit");
                    shown.AddRange(visible);
                } while (page.Move(1));
                Program.Check(shown.SequenceEqual(data), $"{count} ranking rows: all entries are reachable once without skipped or duplicate rows");
                Program.Check(!page.CanNext && !page.Move(1), $"{count} ranking rows: cannot move past the last page");
                var reverseStarts = new List<int> { page.Offset };
                while (page.Move(-1)) reverseStarts.Add(page.Offset);
                forwardStarts.Reverse();
                Program.Check(reverseStarts.SequenceEqual(forwardStarts) && page.Page == 0,
                    $"{count} ranking rows: previous visits the same pages and returns to the first");
                if (count <= 10) Program.Check(!page.CanNext && !page.CanPrevious, $"{count} ranking rows: both buttons disabled when everything fits");
            }

            var paging = new LeaderboardPageState();
            paging.SetCount(10);
            Program.Check(paging.PageCount == 1 && paging.Offset == 0 && !paging.Move(1),
                "all ten ranking rows remain on the first page as in the original leaderboard");
            paging.SetCount(11); paging.Move(1);
            Program.Check(paging.Offset == 10 && paging.PageCount == 2 && paging.Count - paging.Offset == 1,
                "eleven ranking rows use a full ten-row first page and one final row");
            paging.SetCount(11);
            Program.Check(paging.Page == 1 && paging.Offset == 10, "refreshing the same eleven-row ranking preserves its second page");
            paging.SetCount(21);
            Program.Check(paging.Page == 1 && paging.CanNext, "new results preserve the current page and enable the next page");
            paging.Move(1);
            Program.Check(paging.PageCount == 3 && paging.Offset == 20 && paging.Count - paging.Offset == 1 && !paging.CanNext,
                "twenty-one ranking rows use two full ten-row pages and one final row");
            paging.SetCount(20);
            Program.Check(paging.Page == 1 && !paging.CanNext && paging.CanPrevious, "removing the last result clamps the page to the new end");
            paging.SetCount(10);
            Program.Check(paging.Page == 0 && !paging.CanNext && !paging.CanPrevious, "shrinking to a single page restores the first page and both button states");
            paging.SetCount(21); paging.Move(1); paging.Reset(); paging.SetCount(11);
            Program.Check(paging.Page == 0 && paging.CanNext && !paging.CanPrevious, "changing the ranking target resets pagination without disabling a valid next page");
            paging.Move(1); paging.SetCount(0);
            Program.Check(paging.Page == 0 && paging.Count == 0 && !paging.CanNext && !paging.CanPrevious,
                "an empty refreshed ranking clears paging without retaining an invalid offset");
        }
    }
}

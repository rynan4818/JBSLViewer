using System;

namespace JBSLViewer.Models
{
    public sealed class LeaderboardPageState
    {
        // Preserve the original JBSL leaderboard's ten-record pages.
        public const int PageSize = 10;
        public int Page { get; private set; }
        public int Count { get; private set; }
        public int PageCount => Math.Max(1, (Count - 1) / PageSize + 1);
        public int Offset => Page * PageSize;
        public bool CanPrevious => Page > 0;
        public bool CanNext => Page + 1 < PageCount;

        public void Reset() { Page = 0; Count = 0; }
        public void SetCount(int count)
        {
            Count = Math.Max(0, count);
            SetPage(Page);
        }
        public bool SetPage(int page)
        {
            var next = Math.Max(0, Math.Min(page, PageCount - 1));
            if (next == Page) return false;
            Page = next;
            return true;
        }
        public bool Move(int direction) => SetPage(Page + Math.Sign(direction));
    }
}

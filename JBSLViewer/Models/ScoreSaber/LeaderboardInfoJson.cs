using System;
using System.Collections.Generic;

namespace JBSLViewer.Models.ScoreSaber
{
    //API変更の影響を最小限にするため、使用しないプロパティはコメントアウトしています
    //また、コメントアウトした物はNULL仕様の確認がいい加減なので、確認してからコメントアウトを外してください
    public class LeaderboardInfoJson
    {
        //public int id { get; set; }
        public string songHash { get; set; }
        //public string songName { get; set; }
        //public string songSubName { get; set; }
        //public string songAuthorName { get; set; }
        //public string levelAuthorName { get; set; }
        //public Difficulty difficulty { get; set; }
        //public int maxScore { get; set; }
        //public DateTime createdDate { get; set; }
        //public object rankedDate { get; set; }
        //public object qualifiedDate { get; set; }
        //public object lovedDate { get; set; }
        //public bool ranked { get; set; }
        //public bool qualified { get; set; }
        //public bool loved { get; set; }
        //public int maxPP { get; set; }
        //public int stars { get; set; }
        //public int plays { get; set; }
        //public int dailyPlays { get; set; }
        //public bool positiveModifiers { get; set; }
        //public object playerScore { get; set; }
        //public string coverImage { get; set; }
        //public List<Difficulty> difficulties { get; set; }
    }

    public class Difficulty
    {
        //public int leaderboardId { get; set; }
        //public int difficulty { get; set; }
        //public string gameMode { get; set; }
        //public string difficultyRaw { get; set; }
    }
}

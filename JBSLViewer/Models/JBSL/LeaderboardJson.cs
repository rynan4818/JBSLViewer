using System;
using System.Collections.Generic;
using Newtonsoft.Json;
using JBSLViewer.Qualifier.Core.Contracts;

namespace JBSLViewer.Models.JBSL
{
    //API変更の影響を最小限にするため、使用しないプロパティはコメントアウトしています
    //また、コメントアウトした物はNULL仕様の確認がいい加減なので、確認してからコメントアウトを外してください
    public class LeaderboardJson
    {
        //public int league_id { get; set; }
        //public string league_title { get; set; }
        public List<Score> total_rank { get; set; }
        public List<Map> maps { get; set; }
        public DateTime jbslViewerGetTime { get; set; }
        // Only the strict, validated contract may authorize a challenge.
        [JsonIgnore] public string qualifierSourceJson { get; set; }
        [JsonIgnore] public LeaderboardContract qualifierContract { get; set; }
        [JsonIgnore] public string qualifierValidationError { get; set; }
    }

    public class Map
    {
        public string title { get; set; }
        public string lid { get; set; }
        //public string bsr { get; set; }
        public string hash { get; set; }
        public string characteristic { get; set; }
        public string difficulty { get; set; }
        public List<Score> scores { get; set; }
    }

    public class Score
    {
        public int standing { get; set; }
        public string sid { get; set; }
        public string name { get; set; }
        public float acc { get; set; }
        public int pos { get; set; }
        public int miss { get; set; }
        public int rawScore { get; set; }
    }
}

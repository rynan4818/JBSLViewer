using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using JBSLViewer.Qualifier.Core.Contracts;
namespace JBSLViewer.Qualifier.Core.Outbox {
    public class OutboxStore {
        private readonly string _directory;
        private readonly object _sync=new object();
        private HashSet<string> _deleted;
        public long CapacityBytes { get; set; } = 1024L*1024*1024;
        public string DirectoryPath { get { return _directory; } }
        public OutboxStore(string directory) { _directory=Path.GetFullPath(directory);Directory.CreateDirectory(_directory); }
        private HashSet<string> Deleted { get { if(_deleted==null) { var p=Path.Combine(_directory,"deleted.json");_deleted=File.Exists(p)?new HashSet<string>(Newtonsoft.Json.JsonConvert.DeserializeObject<string[]>(File.ReadAllText(p))):new HashSet<string>(); } return _deleted; } }
        private string PathFor(string id) { Guid guid;if(!Guid.TryParse(id,out guid)) throw new ArgumentException("Invalid local result ID"); return Path.Combine(_directory,guid.ToString()+".json"); }
        public virtual bool HasCapacity() {
            lock(_sync) {
                var used=Directory.EnumerateFiles(_directory).Sum(p=>new FileInfo(p).Length);
                var free=new DriveInfo(Path.GetPathRoot(_directory)).AvailableFreeSpace;
                // JSON base64 overhead is included in the reservation margin.
                const long margin=24L*1024*1024;return CapacityBytes-used>=margin && free>=margin;
            }
        }
        public virtual void Save(OutboxEntry entry) { lock(_sync) { if(Deleted.Contains(entry.Id)) return; AtomicWrite(PathFor(entry.Id),StrictJson.Serialize(entry)); } }
        public bool IsDeleted(string id) { lock(_sync) return Deleted.Contains(id); }
        public virtual IList<OutboxEntry> Load() {
            lock(_sync) {
                var results=new List<OutboxEntry>();
                foreach(var path in Directory.EnumerateFiles(_directory,"*.json")) {
                    Guid id;if(!Guid.TryParse(Path.GetFileNameWithoutExtension(path),out id) || Deleted.Contains(id.ToString())) continue;
                    // Invalid durable files must block new reservations rather than silently losing results.
                    try { var entry=Newtonsoft.Json.JsonConvert.DeserializeObject<OutboxEntry>(File.ReadAllText(path),StrictJson.Settings); if(entry==null || entry.Id!=id.ToString() || entry.MetadataJson==null && entry.State!="sent") throw new FormatException("Invalid envelope"); entry.Persisted=true;if(entry.State=="sending") entry.State="pending";results.Add(entry); }
                    catch { results.Add(new OutboxEntry {Id=id.ToString(),State="stopped",ErrorCode="outbox_corrupt",Persisted=true}); }
                }
                return results;
            }
        }
        public virtual void Delete(IEnumerable<string> ids) {
            lock(_sync) {
                var list=ids.ToArray();var nextDeleted=new HashSet<string>(Deleted);foreach(var id in list) { PathFor(id);nextDeleted.Add(id); }
                AtomicWrite(Path.Combine(_directory,"deleted.json"),StrictJson.Serialize(nextDeleted.ToArray()));_deleted=nextDeleted;
                foreach(var id in list) { var p=PathFor(id);if(File.Exists(p)) File.Delete(p);foreach(var temp in Directory.EnumerateFiles(_directory,id+".json.*.tmp")) File.Delete(temp); }
            }
        }
        protected virtual void AtomicWrite(string path,string data) {
            var temp=path+"."+Guid.NewGuid().ToString("N")+".tmp";
            try {
                using(var file=new FileStream(temp,FileMode.CreateNew,FileAccess.Write,FileShare.None)) { var bytes=new UTF8Encoding(false).GetBytes(data);file.Write(bytes,0,bytes.Length);file.Flush(true); }
                if(File.Exists(path)) File.Replace(temp,path,null);else File.Move(temp,path);
            } finally { if(File.Exists(temp)) File.Delete(temp); }
        }
    }
}

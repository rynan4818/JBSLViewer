using System;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text;
using JBSLViewer.Qualifier.Core.Replay;
namespace JBSLViewer.Qualifier.Tests {
    // Independent BSOR V1 layout reader: checks the production encoder fixture against the wire specification.
    internal static class ReplayScenarios {
        private static string Text(BinaryReader r) { var length=r.ReadInt32();if(length<0 || length>16384) throw new FormatException("Invalid BSOR string length");var bytes=r.ReadBytes(length);if(bytes.Length!=length) throw new EndOfStreamException();return new UTF8Encoding(false,true).GetString(bytes); }
        private static void Skip(BinaryReader r,int n) { if(r.ReadBytes(n).Length!=n) throw new EndOfStreamException(); }
        public static void Run() {
            var bytes=File.ReadAllBytes(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"Fixtures","encoder-all-sections.bsor"));
            Validate(bytes);
            var replay=new Replay();replay.info.playerID="76561198000000001";replay.info.playerName="検証🎵";replay.info.hash=new string('A',40);replay.info.difficulty="ExpertPlus";replay.info.mode="Standard";replay.info.score=1150;
            replay.frames.Add(new Frame {head=new Transform(),leftHand=new Transform(),rightHand=new Transform()});
            for(int type=0;type<4;type++) replay.notes.Add(new NoteEvent {eventType=(NoteEventType)type,noteCutInfo=new NoteCutInfo {cutDistanceToCenterPositive=true,beforeCutRating=1.2f,afterCutRating=1.3f}});
            replay.walls.Add(new WallEvent());replay.heights.Add(new AutomaticHeight());replay.pauses.Add(new Pause {duration=15});
            var generated=ReplayEncoder.Encode(replay);Program.Check(generated.Length>0,"current production encoder emits live test data");Validate(generated);
            byte[] compressed;using(var output=new MemoryStream()) { using(var gzip=new GZipStream(output,CompressionMode.Compress,true)) gzip.Write(bytes,0,bytes.Length);compressed=output.ToArray(); }
            using(var input=new GZipStream(new MemoryStream(compressed),CompressionMode.Decompress)) using(var decoded=new MemoryStream()) { input.CopyTo(decoded);Program.Check(decoded.ToArray().SequenceEqual(bytes),"BSOR gzip retains wire bytes"); }
        }
        private static void Validate(byte[] bytes) {
            using(var r=new BinaryReader(new MemoryStream(bytes))) {
                Program.Check(r.ReadUInt32()==0x442d3d69 && r.ReadByte()==1 && r.ReadByte()==0,"BSOR V1 magic/version/info");
                var fields=Enumerable.Range(0,13).Select(i=>Text(r)).ToArray();Program.Check(fields[3]=="76561198000000001" && fields[4]=="検証🎵" && fields[9]==new string('A',40) && fields[12]=="ExpertPlus","BSOR UTF8 identity and MapKey fields");
                Program.Check(r.ReadInt32()==1150 && Text(r)=="Standard","BSOR actual score and mode");Text(r);Text(r);Skip(r,21);
                Program.Check(r.ReadByte()==1 && r.ReadInt32()==1,"BSOR frame section count");Skip(r,92);
                Program.Check(r.ReadByte()==2 && r.ReadInt32()==4,"BSOR note section count");
                for(int expected=0;expected<4;expected++) { Skip(r,12);var type=r.ReadInt32();Program.Check(type==expected,"BSOR note event type "+expected);if(type<2) { Skip(r,4);var speedBits=r.ReadInt32();Skip(r,56);var before=r.ReadSingle();var after=r.ReadSingle();Program.Check((speedBits&1)==1 && Math.Abs(before-1.2f)<0.0001 && Math.Abs(after-1.3f)<0.0001,"BSOR cut info layout/swing/center flag "+expected); } }
                Program.Check(r.ReadByte()==3 && r.ReadInt32()==1,"BSOR wall section count");Skip(r,16);Program.Check(r.ReadByte()==4 && r.ReadInt32()==1,"BSOR height section count");Skip(r,8);
                Program.Check(r.ReadByte()==5 && r.ReadInt32()==1 && r.ReadInt64()==15,"BSOR pause duration is Int64 seconds");Skip(r,4);Program.Check(r.BaseStream.Position==bytes.Length,"BSOR sections consume exact payload");
            }
        }
    }
}

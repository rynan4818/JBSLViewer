// Adapted from BeatLeader: https://github.com/BeatLeader/beatleader-mod/blob/1291supportx/LICENSE
// Copyright (c) 2023 BeatLeader. MIT License; see THIRD-PARTY-NOTICES.txt in the distribution.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;

namespace JBSLViewer.Qualifier.Core.Replay {
    public class Replay
    {
        public ReplayInfo info = new ReplayInfo();

        public List<Frame> frames = new List<Frame>();

        public List<NoteEvent> notes = new List<NoteEvent>();
        public List<WallEvent> walls = new List<WallEvent>();
        public List<AutomaticHeight> heights = new List<AutomaticHeight>();
        public List<Pause> pauses = new List<Pause>();
        public SaberOffsets saberOffsets = new SaberOffsets();
        public Dictionary<string, byte[]> customData = new Dictionary<string, byte[]>();
    }
    public class ReplayInfo {
        public string version;
        public string gameVersion;
        public string timestamp;

        public string playerID;
        public string playerName;
        public string platform;

        public string trackingSytem;
        public string hmd;
        public string controller;

        public string hash;
        public string songName;
        public string mapper;
        public string difficulty;

        public int score;
        public string mode;
        public string environment;
        public string modifiers;
        public float jumpDistance;
        public bool leftHanded;
        public float height;

        public float startTime;
        public float failTime;
        public float speed;

        public override string ToString() {
            var line = string.Empty;
            line += $"ModVersion: {version}\r\n";
            line += $"GameVersion: {gameVersion}\r\n";
            line += $"Platform: {platform}\r\n";
            line += $"PlayerID: {playerID}\r\n";
            line += $"SongHash: {hash}\r\n";
            line += $"Mode: {mode}\r\n";
            line += $"Modifiers: {modifiers}\r\n";
            line += $"TotalScore: {score.ToString()}\r\n";
            return line;
        }
    }
    public class Frame
    {
        public float time;
        public int fps;
        public Transform head;
        public Transform leftHand;
        public Transform rightHand;
    }
    public enum NoteEventType
    {
        unknown = -1,
        good = 0,
        bad = 1,
        miss = 2,
        bomb = 3
    }
    public class NoteEvent
    {
        public int noteID;
        public float eventTime;
        public float spawnTime;
        public NoteEventType eventType = NoteEventType.unknown;
        public NoteCutInfo noteCutInfo;
    }
    public class WallEvent
    {
        public int wallID;
        public float energy;
        public float time;
        public float spawnTime;
    }
    public class AutomaticHeight
    {
        public float height;
        public float time;
    }
    public class Pause
    {
        public long duration;
        public float time;
    }
    public class NoteCutInfo
    {        
        public bool speedOK { get; set; }
        public bool directionOK { get; set; }
        public bool saberTypeOK { get; set; }
        public bool wasCutTooSoon { get; set; }
        public float saberSpeed { get; set; }
        public bool cutDistanceToCenterPositive { get; set; }
        public Vector3 saberDir { get; set; }
        public int saberType { get; set; }
        public float timeDeviation { get; set; }
        public float cutDirDeviation { get; set; }
        public Vector3 cutPoint { get; set; }
        public Vector3 cutNormal { get; set; }
        public float cutDistanceToCenter { get; set; }
        public float cutAngle{ get; set; }
        public float beforeCutRating{ get; set; }
        public float afterCutRating { get; set; }

        public bool allIsOK => speedOK && directionOK && saberTypeOK && !wasCutTooSoon;
    }
    public class SaberOffsets {
        public Vector3 LeftSaberLocalPosition;
        public Quaternion LeftSaberLocalRotation;
        public Vector3 RightSaberLocalPosition;
        public Quaternion RightSaberLocalRotation;
    }
    public enum StructType
    {
        info = 0,
        frames = 1,
        notes = 2,
        walls = 3,
        heights = 4,
        pauses = 5,
        saberOffsets = 6,
        customData = 7
    }
    public struct Vector3
    {
        public Vector3(float x, float y, float z)
        {
            this.x = x;
            this.y = y;
            this.z = z;
        }


        public float x;
        public float y;
        public float z;
    }
    public struct Quaternion
    {
        public Quaternion(float x, float y, float z, float w)
        {
            this.x = x;
            this.y = y;
            this.z = z;
            this.w = w;
        }


        public float x;
        public float y;
        public float z;
        public float w;
    }
    public class Transform
    {
        public Transform() { }
        public Transform(Vector3 position, Quaternion rotation)
        {
            this.position = position;
            this.rotation = rotation;
        }



        public Vector3 position;
        public Quaternion rotation;
    }
    public static class ReplayEncoder
    {
        public static void Encode(Replay replay, BinaryWriter stream)
        {
            stream.Write(0x442d3d69);
            stream.Write((byte)1);

            for (int a = 0; a <= (int)StructType.pauses; a++)
            {
                StructType type = (StructType)a;
                stream.Write((byte)a);

                switch (type)
                {
                    case StructType.info:
                        EncodeInfo(replay.info, stream);
                        break;
                    case StructType.frames:
                        EncodeFrames(replay.frames, stream);
                        break;
                    case StructType.notes:
                        EncodeNotes(replay.notes, stream);
                        break;
                    case StructType.walls:
                        EncodeWalls(replay.walls, stream);
                        break;
                    case StructType.heights:
                        EncodeHeights(replay.heights, stream);
                        break;
                    case StructType.pauses:
                        EncodePauses(replay.pauses, stream);
                        break;
                    case StructType.saberOffsets:
                        EncodeSaberOffsets(replay.saberOffsets, stream);
                        break;
                    case StructType.customData:
                        EncodeCustomData(replay.customData, stream);
                        break;
                }
            }
        }

        static void EncodeInfo(ReplayInfo info, BinaryWriter stream)
        {
            EncodeString(info.version, stream);
            EncodeString(info.gameVersion, stream);
            EncodeString(info.timestamp, stream);

            EncodeString(info.playerID, stream);
            EncodeString(info.playerName, stream);
            EncodeString(info.platform, stream);

            EncodeString(info.trackingSytem, stream);
            EncodeString(info.hmd, stream);
            EncodeString(info.controller, stream);

            EncodeString(info.hash, stream);
            EncodeString(info.songName, stream);
            EncodeString(info.mapper, stream);
            EncodeString(info.difficulty, stream);

            stream.Write(info.score);
            EncodeString(info.mode, stream);
            EncodeString(info.environment, stream);
            EncodeString(info.modifiers, stream);
            stream.Write(info.jumpDistance);
            stream.Write(info.leftHanded);
            stream.Write(info.height);

            stream.Write(info.startTime);
            stream.Write(info.failTime);
            stream.Write(info.speed);
        }

        static void EncodeFrames(List<Frame> frames, BinaryWriter stream)
        {
            stream.Write((uint)frames.Count);
            foreach (var frame in frames)
            {
                stream.Write(frame.time);
                stream.Write(frame.fps);
                EncodeVector(frame.head.position, stream);
                EncodeQuaternion(frame.head.rotation, stream);
                EncodeVector(frame.leftHand.position, stream);
                EncodeQuaternion(frame.leftHand.rotation, stream);
                EncodeVector(frame.rightHand.position, stream);
                EncodeQuaternion(frame.rightHand.rotation, stream);
            }
        }

        static void EncodeNotes(List<NoteEvent> notes, BinaryWriter stream)
        {
            stream.Write((uint)notes.Count);
            foreach (var note in notes)
            {
                stream.Write(note.noteID);
                stream.Write(note.eventTime);
                stream.Write(note.spawnTime);
                stream.Write((int)note.eventType);
                if (note.eventType == NoteEventType.good || note.eventType == NoteEventType.bad)
                {
                    EncodeNoteInfo(note.noteCutInfo, stream);
                }
            }
        }

        static void EncodeWalls(List<WallEvent> walls, BinaryWriter stream)
        {
            stream.Write((uint)walls.Count);
            foreach (var wall in walls)
            {
                stream.Write(wall.wallID);
                stream.Write(wall.energy);
                stream.Write(wall.time);
                stream.Write(wall.spawnTime);
            }
        }

        static void EncodeHeights(List<AutomaticHeight> heights, BinaryWriter stream)
        {
            stream.Write((uint)heights.Count);
            foreach (var height in heights)
            {
                stream.Write(height.height);
                stream.Write(height.time);
            }
        }

        static void EncodePauses(List<Pause> pauses, BinaryWriter stream)
        {
            stream.Write((uint)pauses.Count);
            foreach (var pause in pauses)
            {
                stream.Write(pause.duration);
                stream.Write(pause.time);
            }
        }

        static void EncodeSaberOffsets(SaberOffsets saberOffsets, BinaryWriter stream)
        {
            EncodeVector(saberOffsets.LeftSaberLocalPosition, stream);
            EncodeQuaternion(saberOffsets.LeftSaberLocalRotation, stream);
            EncodeVector(saberOffsets.RightSaberLocalPosition, stream);
            EncodeQuaternion(saberOffsets.RightSaberLocalRotation, stream);
        }

        static void EncodeCustomData(Dictionary<string, byte[]> customData, BinaryWriter stream)
        {
            stream.Write(customData.Count);
            foreach (var pair in customData) {
                EncodeString(pair.Key, stream);
                EncodeByteArray(pair.Value, stream);
            }
        }

        static void EncodeNoteInfo(NoteCutInfo info, BinaryWriter stream)
        {
            stream.Write(info.speedOK);
            stream.Write(info.directionOK);
            stream.Write(info.saberTypeOK);
            stream.Write(info.wasCutTooSoon);
            stream.Write(IncorporateBool(info.saberSpeed, info.cutDistanceToCenterPositive));
            EncodeVector(info.saberDir, stream);
            stream.Write(info.saberType);
            stream.Write(info.timeDeviation);
            stream.Write(info.cutDirDeviation);
            EncodeVector(info.cutPoint, stream);
            EncodeVector(info.cutNormal, stream);
            stream.Write(info.cutDistanceToCenter);
            stream.Write(info.cutAngle);
            stream.Write(info.beforeCutRating);
            stream.Write(info.afterCutRating);
        }

        private static float IncorporateBool(float value, bool flag)
        {
            var bits = BitConverter.ToInt32(BitConverter.GetBytes(value), 0);
            bits = flag ? bits | 1 : bits & ~1;
            return BitConverter.ToSingle(BitConverter.GetBytes(bits), 0);
        }

        public static byte[] Encode(Replay replay)
        {
            using (var stream = new MemoryStream())
            {
                using (var writer = new BinaryWriter(stream, Encoding.UTF8, true)) Encode(replay, writer);
                return stream.ToArray();
            }
        }

        static void EncodeString(string value, BinaryWriter stream)
        {
            string toEncode = value != null ? value : "";
            var bytes = Encoding.UTF8.GetBytes(toEncode);
            stream.Write(bytes.Length);
            stream.Write(bytes);
        }

        static void EncodeByteArray(byte[] value, BinaryWriter stream)
        {
            stream.Write(value.Length);
            stream.Write(value);
        }

        static void EncodeVector(Vector3 vector, BinaryWriter stream)
        {
            stream.Write(vector.x);
            stream.Write(vector.y);
            stream.Write(vector.z);
        }

        static void EncodeQuaternion(Quaternion quaternion, BinaryWriter stream)
        {
            stream.Write(quaternion.x);
            stream.Write(quaternion.y);
            stream.Write(quaternion.z);
            stream.Write(quaternion.w);
        }
    }
}


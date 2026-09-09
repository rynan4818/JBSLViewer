// Adapted from BeatLeader: https://github.com/BeatLeader/beatleader-mod/blob/1291supportx/LICENSE
// Copyright (c) 2023 BeatLeader. MIT License; see THIRD-PARTY-NOTICES.txt in the distribution.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using IPA.Utilities;
using JBSLViewer.Qualifier.Core;
using JBSLViewer.Qualifier.Replay;
using UnityEngine;
using UnityEngine.XR;
using Zenject;
using R = JBSLViewer.Qualifier.Core.Replay;

namespace JBSLViewer.Qualifier
{
    // All game reads happen on the Unity thread. StopAndDetach transfers exclusive ownership
    // of the DTO to the result pipeline; no game references escape with that snapshot.
    public sealed class QualifierReplayRecorder : ILateTickable, IDisposable
    {
        [Inject] private SaberManager _sabers;
        [Inject] private PlayerTransforms _transforms;
        [Inject] private BeatmapObjectManager _objects;
        [Inject] private BeatmapObjectSpawnController _spawn;
        [Inject] private AudioTimeSyncController _time;
        [Inject] private ScoreController _score;
        [Inject] private PlayerHeadAndObstacleInteraction _headObstacle;
        [Inject] private GameEnergyCounter _energy;
        [Inject] private GameplayCoreSceneSetupData _setup;
        [Inject] private IVRPlatformHelper _vr;
        [InjectOptional] private PlayerHeightDetector _height;
        [InjectOptional] private PauseController _pause;
        public static QualifierReplayRecorder Current { get; private set; }
        public static bool IsRecording => Current != null && Current._recording;
        public bool ScoringStarted { get; private set; }
        public bool GenerationFailed { get; private set; }
        public bool PauseTrackingAvailable { get; private set; }
        public int PauseCount { get; private set; }
        public double TotalPauseSeconds { get; private set; }
        public float SongTime => _time.songTime;
        private R.Replay _replay;
        private bool _recording;
        private bool _subscribed;
        private readonly Dictionary<NoteData, R.NoteEvent> _notes = new Dictionary<NoteData, R.NoteEvent>();
        private readonly HashSet<R.NoteEvent> _queued = new HashSet<R.NoteEvent>();
        private readonly Dictionary<ObstacleController, R.WallEvent> _walls = new Dictionary<ObstacleController, R.WallEvent>();
        private R.WallEvent _currentWall;
        private R.Pause _currentPause;
        private long _pauseStart;
        private Transform _origin, _head, _left, _right;
        private int _lastScore;
        private float _lastEnergy;
        private GameplayModifiers _recordedModifiers;

        public void Begin(ChallengeContext context, IQualifierGameplayHost host)
        {
            if (_recording || _subscribed) throw new InvalidOperationException("Recorder already bound.");
            _replay = new R.Replay();
            _lastScore = _score.multipliedScore;
            _lastEnergy = _energy.energy;
            _recordedModifiers = _setup.gameplayModifiers.CopyWith();
            var info = _replay.info;
            info.version = host.ClientVersion;
            info.gameVersion = Application.version;
            info.timestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds().ToString(System.Globalization.CultureInfo.InvariantCulture);
            info.playerID = context.OwnerSid;
            info.playerName = host.PlayerName;
            info.platform = host.Platform;
            info.hash = context.Map.Hash;
            info.mode = context.Map.Characteristic;
            info.difficulty = context.Map.Difficulty;
            info.songName = _setup.previewBeatmapLevel.songName;
            info.mapper = _setup.previewBeatmapLevel.levelAuthorName;
            info.environment = _setup.environmentInfo.environmentName;
            info.leftHanded = _setup.playerSpecificSettings.leftHanded;
            info.height = _setup.playerSpecificSettings.automaticPlayerHeight ? 0 : _setup.playerSpecificSettings.playerHeight;
            info.jumpDistance = _spawn.jumpDistance;
            info.trackingSytem = _vr.vrPlatformSDK.ToString();
            var devices = new List<InputDevice>();
            InputDevices.GetDevicesAtXRNode(XRNode.Head, devices);
            info.hmd = devices.FirstOrDefault().name ?? "Unknown";
            devices.Clear();
            InputDevices.GetDevicesAtXRNode(XRNode.RightHand, devices);
            info.controller = devices.FirstOrDefault().name ?? "Unknown";
            _origin = _transforms.GetField<Transform, PlayerTransforms>("_originParentTransform");
            _head = _transforms.GetField<Transform, PlayerTransforms>("_headTransform");
            _left = _sabers.leftSaber.transform;
            _right = _sabers.rightSaber.transform;
            _objects.noteWasAddedEvent += NoteAdded;
            _objects.noteWasCutEvent += NoteCut;
            _objects.obstacleWasSpawnedEvent += WallSpawned;
            _score.scoringForNoteFinishedEvent += ScoringFinished;
            _spawn.didInitEvent += SpawnInitialized;
            _headObstacle.headDidEnterObstacleEvent += WallEntered;
            if (_height != null) _height.playerHeightDidChangeEvent += HeightChanged;
            if (_pause != null) { _pause.didPauseEvent += Paused; _pause.didResumeEvent += Resumed; }
            _subscribed = _recording = true;
            PauseTrackingAvailable = _pause != null;
            Current = this;
            if (_pause == null) RecordingError(new InvalidOperationException("Solo pause controller was unavailable."));
            if (_setup.playerSpecificSettings.automaticPlayerHeight)
            {
                if (_height == null) RecordingError(new InvalidOperationException("Automatic player height detector was unavailable."));
                else HeightChanged(_height.playerHeight);
            }
        }

        public void LateTick()
        {
            if (!_recording || _currentPause != null) return;
            try
            {
                _lastScore = _score.multipliedScore;
                _lastEnergy = _energy.energy;
                _replay.frames.Add(new R.Frame {
                    time = _time.songTime, fps = Time.deltaTime > 0 ? Mathf.RoundToInt(1f / Time.deltaTime) : 0,
                    head = Pose(_head), leftHand = Pose(_left), rightHand = Pose(_right)
                });
                if (_currentWall != null && !_headObstacle.playerHeadIsInObstacle)
                { _currentWall.energy = _energy.energy; _currentWall = null; }
            }
            catch (Exception ex) { RecordingError(ex); }
        }

        private R.Transform Pose(Transform transform) => new R.Transform(
            Vector(_origin.InverseTransformPoint(transform.position)),
            Quaternion(UnityEngine.Quaternion.Inverse(_origin.rotation) * transform.rotation));
        private static R.Vector3 Vector(UnityEngine.Vector3 v) => new R.Vector3(v.x, v.y, v.z);
        private static R.Quaternion Quaternion(UnityEngine.Quaternion q) => new R.Quaternion(q.x, q.y, q.z, q.w);
        private void SpawnInitialized() { if (_recording) _replay.info.jumpDistance = _spawn.jumpDistance; }
        private void HeightChanged(float height)
        { if (_recording) _replay.heights.Add(new R.AutomaticHeight { height = height, time = _time.songTime }); }

        private void NoteAdded(NoteData data, BeatmapObjectSpawnMovementData.NoteSpawnData spawn, float rotation)
        {
            if (!_recording) return;
            _notes[data] = new R.NoteEvent {
                noteID = ((int)data.scoringType + 2) * 10000 + data.lineIndex * 1000 + (int)data.noteLineLayer * 100
                         + (int)data.colorType * 10 + (int)data.cutDirection,
                spawnTime = data.time
            };
        }
        private void NoteCut(NoteController controller, in NoteCutInfo cut)
        {
            if (!_recording) return;
            if (!_notes.TryGetValue(cut.noteData, out var note)) { RecordingError(new InvalidOperationException("Cut has no spawn event.")); return; }
            note.noteCutInfo = new R.NoteCutInfo {
                speedOK = cut.speedOK, directionOK = cut.directionOK, saberTypeOK = cut.saberTypeOK,
                wasCutTooSoon = cut.wasCutTooSoon, saberSpeed = cut.saberSpeed, saberDir = Vector(cut.saberDir),
                saberType = (int)cut.saberType, timeDeviation = cut.timeDeviation, cutDirDeviation = cut.cutDirDeviation,
                cutPoint = Vector(cut.cutPoint), cutNormal = Vector(cut.cutNormal), cutDistanceToCenter = cut.cutDistanceToCenter,
                cutAngle = cut.cutAngle,
                cutDistanceToCenterPositive = UnityEngine.Vector3.Dot(cut.cutNormal, cut.cutPoint - controller.noteTransform.position) <= 0
            };
        }

        // Called by a read-only ScoreController.LateUpdate prefix to retain scoring order.
        internal void BeforeScoring(ScoreController controller, AudioTimeSyncController time,
            List<float> pendingNoteTimes, List<ScoringElement> scoring)
        {
            if (!_recording || controller != _score) return;
            try
            {
                var nearest = pendingNoteTimes.Count > 0 ? pendingNoteTimes[0] : float.MaxValue;
                foreach (var element in scoring)
                {
                    if (element.time >= time.songTime + .15f && element.time <= nearest) break;
                    if (element is MissScoringElement && element.noteData.scoringType == NoteData.ScoringType.NoScore) continue;
                    ScoringStarted = true;
                    if (!_notes.TryGetValue(element.noteData, out var note)) throw new InvalidOperationException("Scoring has no spawn event.");
                    if (_queued.Add(note)) { note.eventTime = time.songTime; _replay.notes.Add(note); }
                }
            }
            catch (Exception ex) { RecordingError(ex); }
        }
        private void ScoringFinished(ScoringElement element)
        {
            if (!_recording) return;
            try
            {
                if (element is MissScoringElement && element.noteData.scoringType == NoteData.ScoringType.NoScore) return;
                ScoringStarted = true;
                var note = _notes[element.noteData];
                bool bomb = element.noteData.colorType == ColorType.None;
                if (element is MissScoringElement) { if (!bomb) note.eventType = R.NoteEventType.miss; }
                else if (element is BadCutScoringElement) note.eventType = bomb ? R.NoteEventType.bomb : R.NoteEventType.bad;
                else if (element is GoodCutScoringElement good)
                {
                    var buffer = good.GetField<CutScoreBuffer, GoodCutScoringElement>("_cutScoreBuffer");
                    var counter = buffer.GetField<SaberSwingRatingCounter, CutScoreBuffer>("_saberSwingRatingCounter");
                    SwingRatingEnhancer.Enhance(note.noteCutInfo, counter);
                    SwingRatingEnhancer.Reset(counter);
                    note.eventType = R.NoteEventType.good;
                }
            }
            catch (Exception ex) { RecordingError(ex); }
        }
        private void WallSpawned(ObstacleController obstacle)
        {
            if (!_recording) return;
            var data = obstacle.obstacleData;
            _walls[obstacle] = new R.WallEvent { wallID = data.lineIndex * 100 + (int)data.type * 10 + data.width, spawnTime = data.time };
        }
        private void WallEntered(ObstacleController obstacle)
        {
            if (!_recording || _currentWall != null) return;
            if (!_walls.TryGetValue(obstacle, out var spawned)) { RecordingError(new InvalidOperationException("Wall has no spawn event.")); return; }
            // A second entry into the same wall must not mutate the earlier recorded event.
            _currentWall = new R.WallEvent { wallID = spawned.wallID, spawnTime = spawned.spawnTime, time = _time.songTime, energy = _energy.energy };
            _replay.walls.Add(_currentWall);
        }
        private void Paused()
        {
            if (!_recording || _currentPause != null) return;
            _currentPause = new R.Pause { time = _time.songTime };
            _pauseStart = Stopwatch.GetTimestamp();
            PauseCount++;
        }
        private void Resumed()
        {
            if (_currentPause == null) return;
            var seconds = (Stopwatch.GetTimestamp() - _pauseStart) / (double)Stopwatch.Frequency;
            TotalPauseSeconds += seconds;
            _currentPause.duration = (long)seconds;
            _replay.pauses.Add(_currentPause);
            _currentPause = null;
        }
        internal void RecordingError(Exception ex)
        {
            if (GenerationFailed) return;
            GenerationFailed = true;
            Plugin.Log.Error("Qualifier replay capture failed: " + ex);
        }
        public R.Replay StopAndDetach(LevelCompletionResults results)
        {
            if (_replay == null) return null;
            Resumed();
            if (_currentWall != null) _currentWall.energy = results != null ? results.energy : _lastEnergy;
            _recording = false;
            Unsubscribe();
            if (Current == this) Current = null;
            _replay.notes.RemoveAll(x => x.eventType == R.NoteEventType.unknown);
            _replay.info.score = results != null ? results.multipliedScore : _lastScore;
            _replay.info.modifiers = string.Join(",", ModifierCodes(_recordedModifiers, results != null ? results.energy : _lastEnergy));
            if (results != null && results.levelEndStateType == LevelCompletionResults.LevelEndStateType.Failed) _replay.info.failTime = results.endSongTime;
            var result = GenerationFailed ? null : _replay;
            _replay = null;
            SwingRatingEnhancer.preSwingMap.Clear(); SwingRatingEnhancer.postSwingMap.Clear();
            return result;
        }
        public static string[] ModifierCodes(GameplayModifiers m, float energy)
        {
            var result = new List<string>();
            if (m.disappearingArrows) result.Add("DA");
            if (m.songSpeed == GameplayModifiers.SongSpeed.Faster) result.Add("FS");
            if (m.songSpeed == GameplayModifiers.SongSpeed.Slower) result.Add("SS");
            if (m.songSpeed == GameplayModifiers.SongSpeed.SuperFast) result.Add("SF");
            if (m.ghostNotes) result.Add("GN"); if (m.noArrows) result.Add("NA"); if (m.noBombs) result.Add("NB");
            if (m.noFailOn0Energy && energy == 0) result.Add("NF");
            if (m.enabledObstacleType == GameplayModifiers.EnabledObstacleType.NoObstacles) result.Add("NO");
            if (m.strictAngles) result.Add("SA"); if (m.smallCubes) result.Add("SC"); if (m.proMode) result.Add("PM");
            if (m.failOnSaberClash) result.Add("CS"); if (m.instaFail) result.Add("IF");
            if (m.energyType == GameplayModifiers.EnergyType.Battery) result.Add("BE");
            return result.ToArray();
        }
        private void Unsubscribe()
        {
            if (!_subscribed) return;
            _subscribed = false;
            _objects.noteWasAddedEvent -= NoteAdded; _objects.noteWasCutEvent -= NoteCut;
            _objects.obstacleWasSpawnedEvent -= WallSpawned; _score.scoringForNoteFinishedEvent -= ScoringFinished;
            _spawn.didInitEvent -= SpawnInitialized; _headObstacle.headDidEnterObstacleEvent -= WallEntered;
            if (_height != null) _height.playerHeightDidChangeEvent -= HeightChanged;
            if (_pause != null) { _pause.didPauseEvent -= Paused; _pause.didResumeEvent -= Resumed; }
        }
        public void Dispose()
        {
            _recording = false; Unsubscribe();
            if (Current == this) Current = null;
        }
    }
}

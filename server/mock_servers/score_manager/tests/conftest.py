from __future__ import annotations

import gzip
import json
import struct
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mock_servers.score_manager.config import ROOT, Settings
from mock_servers.score_manager.score_manager_server import create_app


class Clock:
    def __init__(self, value: datetime): self.value = value
    def __call__(self): return self.value


class FakeLeaderboardClient:
    def __init__(self, projections):
        self.projections = projections; self.calls = 0; self.error = None; self.lock = threading.Lock()
    def _get(self, league_id):
        with self.lock: self.calls += 1
        if self.error: raise self.error
        if league_id not in self.projections:
            from mock_servers.score_manager.errors import ApiProblem
            raise ApiProblem(404, "league_not_found", "missing")
        return json.loads(json.dumps(self.projections[league_id]))
    def get_sync(self, league_id): return self._get(league_id)
    async def get_async(self, league_id): return self._get(league_id)


def fixture_projections():
    return {lid: json.loads((Path(__file__).parent / "fixtures" / f"leaderboard_{lid}.json").read_text(encoding="utf-8"))
            for lid in (3023, 3024, 3025)}


@pytest.fixture
def server(tmp_path):
    clock = Clock(datetime(2030, 1, 1, tzinfo=timezone.utc))
    settings = Settings(database_path=tmp_path / "score.sqlite3", replay_dir=tmp_path / "replays", rate_limit_enabled=False, allow_insecure_loopback_cookie=True, clock=clock)
    upstream = FakeLeaderboardClient(fixture_projections())
    app = create_app(settings, upstream)
    with TestClient(app) as client:
        yield client, app, settings, upstream, clock


def authenticate(client: TestClient, provider="steamTicket"):
    response = client.post("/api/v1/auth/session", data={"ticket": "contract-ticket", "provider": provider, "returnUrl": "/"})
    assert response.status_code == 200, response.text
    return response


MAP_A = {"hash": "0123456789ABCDEF0123456789ABCDEF01234567", "characteristic": "Standard", "difficulty": "ExpertPlus"}


def reserve(client: TestClient, key="05ec7802-c219-4c73-ad28-9d36c2457349", map_key=None):
    return client.post("/api/v1/qualifiers/challenges", headers={"Idempotency-Key": key}, json={"schemaVersion": 1, "leagueId": 3023, "map": map_key or MAP_A, "clientVersion": "ContractTests/1", "gameVersion": "1.29.1"})


def metadata(challenge_id: str, result_id="75ea0d49-6a2d-4ec1-91c4-2cb9ce85011e", *, ranked=False, end_type="preflight_rejected"):
    return {
        "schemaVersion": 1, "clientResultId": result_id, "challengeId": challenge_id, "map": MAP_A,
        "endState": "incomplete" if end_type == "preflight_rejected" else "cleared", "endAction": "none", "endType": end_type,
        "endSongTime": None, "multipliedScore": None, "modifiedScore": None, "maxPossibleModifiedScore": None,
        "missedCount": None, "badCutsCount": None, "goodCutsCount": None, "maxCombo": None, "fullCombo": None,
        "energy": None, "modifiers": None,
        "submissionEligibility": {"allowedAtStart": ranked, "remainedAllowed": ranked, "blockers": []},
        "scoreValidity": {"validForRanking": ranked, "invalidReason": None if ranked else "preflight_rejected", "restartDetected": False, "playInstanceCount": 1 if ranked else 0},
        "timing": {"confirmedAtClient": None, "reserveResponseReceivedAtClient": None, "startedAtClient": None, "endedAtClient": None, "resultFinalizedAtClient": None, "localSongDurationSeconds": 180.0, "songSpeedMultiplier": 1.0, "totalPauseSeconds": 0.0},
        "clientVersion": "ContractTests/1", "gameVersion": "1.29.1"
    }


def _string(value: str) -> bytes:
    data = value.encode("utf-8"); return struct.pack("<i", len(data)) + data


def valid_bsor(sid="76561198000000000", platform="steam", song_hash=MAP_A["hash"], mode="Standard", difficulty="ExpertPlus") -> bytes:
    info_strings = ["1.0.0", "1.29.1", "2030-01-01T00:00:00Z", sid, "テスト名", platform, "OpenXR", "HMD", "Controller", song_hash, "Song", "Mapper", difficulty]
    data = struct.pack("<iB", 0x442D3D69, 1) + b"\x00" + b"".join(_string(v) for v in info_strings)
    data += struct.pack("<i", 123456) + _string(mode) + _string("DefaultEnvironment") + _string("")
    data += struct.pack("<fBffff", 1.0, 0, 1.7, 0.0, 0.0, 1.0)
    # frames, notes, walls, heights, pauses; zero arrays are valid and exercise every section.
    for section in range(1, 6): data += struct.pack("<BI", section, 0)
    return gzip.compress(data)


def result_files(meta, replay=None):
    files = {"metadata": ("metadata.json", json.dumps(meta), "application/json")}
    if replay is not None: files["replay"] = ("../../unsafe.bsor.gz", replay, "application/gzip")
    return files

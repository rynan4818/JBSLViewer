import copy
import gzip
import json
import struct
import threading
from dataclasses import asdict
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from jbsl_score.admin import create_admin
from jbsl_score.api import create_api
from jbsl_score.config import Config
from jbsl_score.errors import ApiProblem
from jbsl_score.security import Security
from jbsl_score.service import Service, timestamp
from jbsl_score.upstream import Identity

SID = "76561198000000000"
MAP = {"hash": "0123456789ABCDEF0123456789ABCDEF01234567", "characteristic": "Standard", "difficulty": "ExpertPlus"}
NOW = 1893456000.0


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


def projection(now=NOW, limit=3):
    return {
        "league_id": 3023,
        "league_title": "JBSL Test Qualifier",
        "isLive": True,
        "isOpen": True,
        "end": timestamp(now + 3600),
        "qualifier": {
            "enabled": True,
            "submission_method": "jbsl_qualifier_v1",
            "revision": "1",
            "starts_at": timestamp(now - 3600),
            "ends_at": None,
        },
        "participants": [{"sid": SID}, {"sid": "76561198000000001"}],
        "maps": [{**MAP, "title": "Contract song", "qualifier_attempt_limit": limit, "song_duration_seconds": 180.0}],
    }


class Upstream:
    def __init__(self, data=None):
        self.data, self.calls, self.error, self.lock = data or projection(), 0, None, threading.Lock()

    def get(self, league_id):
        with self.lock:
            self.calls += 1
        if self.error:
            raise self.error
        if league_id != self.data["league_id"]:
            raise ApiProblem(404, "league_not_found", "missing")
        return copy.deepcopy(self.data)


class Verifier:
    def verify(self, ticket, provider):
        if provider not in ("steamTicket", "oculusTicket") or ticket not in ("mock-ticket", "other-ticket"):
            raise ApiProblem(401, "invalid_ticket", "invalid")
        sid = SID if ticket == "mock-ticket" else "76561198000000001"
        return Identity(sid, "Test Player", provider)


@pytest.fixture
def server(tmp_path):
    clock, upstream = Clock(), Upstream()
    config = Config(data_dir=tmp_path)
    service = Service(config, upstream, Verifier(), clock)
    policy, version = service.db.policy()
    policy.auth_per_minute = policy.reserve_per_minute = policy.result_per_minute = policy.status_per_minute = 600
    policy.backup_interval_hours = 0
    service.update_policy(asdict(policy), version, "test", "test")
    security = Security(service)
    security.create_admin("operator", "test-admin-password-2026")
    token = security.create_service_token("test-web")
    with (
        TestClient(create_api(service, background=False), base_url=config.api_public_url) as api,
        TestClient(create_admin(service), base_url=config.admin_public_url) as admin,
    ):
        yield api, admin, service, upstream, clock, token


def login(api, other=False):
    response = api.post(
        "/api/v1/auth/session",
        data={"ticket": "other-ticket" if other else "mock-ticket", "provider": "steamTicket", "returnUrl": "/"},
    )
    assert response.status_code == 200, response.text
    return response


def login_admin(admin):
    response = admin.post(
        "/admin/api/login",
        json={"username": "operator", "password": "test-admin-password-2026"},
        headers={"X-JBSL-Admin": "1"},
    )
    assert response.status_code == 200, response.text
    admin.headers["X-CSRF-Token"] = response.json()["csrfToken"]
    return response


def reserve(api, key=None, map_key=None, league=3023):
    return api.post(
        "/api/v1/qualifiers/challenges",
        json={
            "schemaVersion": 1,
            "leagueId": league,
            "map": map_key or MAP,
            "clientVersion": "contract-test",
            "gameVersion": "1.29.1",
        },
        headers={"Idempotency-Key": key or str(uuid4())},
    )


def metadata(challenge_id, end="preflight_rejected", reason=None, score=115):
    endings = {
        "clear": ("cleared", "none"),
        "fail": ("failed", "none"),
        "quit": ("incomplete", "quit"),
        "restart": ("incomplete", "restart"),
        "unknown": ("unknown", "unknown"),
        "preflight_rejected": ("incomplete", "none"),
    }
    reason = reason or {
        "quit": "quit",
        "restart": "restarted",
        "unknown": "unknown",
        "preflight_rejected": "preflight_rejected",
    }.get(end)
    ranked = end in ("clear", "fail") and reason is None
    return {
        "schemaVersion": 1,
        "clientResultId": str(uuid4()),
        "challengeId": challenge_id,
        "map": dict(MAP),
        "endState": endings[end][0],
        "endAction": endings[end][1],
        "endType": end,
        "endSongTime": 1.0,
        "multipliedScore": score if ranked else None,
        "modifiedScore": score if ranked else None,
        "maxPossibleModifiedScore": 115 if ranked else None,
        "missedCount": 0,
        "badCutsCount": 0,
        "goodCutsCount": 1,
        "maxCombo": 1,
        "fullCombo": True,
        "energy": 0.5,
        "modifiers": [],
        "submissionEligibility": {
            "allowedAtStart": reason != "submission_disabled",
            "remainedAllowed": reason != "submission_disabled",
            "blockers": [],
        },
        "scoreValidity": {
            "validForRanking": ranked,
            "invalidReason": reason,
            "restartDetected": end == "restart",
            "playInstanceCount": 0 if end == "preflight_rejected" else 1,
        },
        "timing": {
            "confirmedAtClient": None,
            "reserveResponseReceivedAtClient": None,
            "startedAtClient": None if end == "preflight_rejected" else timestamp(NOW),
            "endedAtClient": timestamp(NOW + 1),
            "resultFinalizedAtClient": timestamp(NOW + 1),
            "localSongDurationSeconds": 180.0,
            "songSpeedMultiplier": 1.0,
            "totalPauseSeconds": 0.0,
        },
        "clientVersion": "contract-test",
        "gameVersion": "1.29.1",
    }


def bsor(sid=SID, score=115, key=None, platform="steam"):
    key = key or MAP

    def string(value):
        encoded = value.encode("utf-8")
        return struct.pack("<i", len(encoded)) + encoded

    values = [
        "1.0.0",
        "1.29.1",
        timestamp(NOW),
        sid,
        "テスト",
        platform,
        "OpenXR",
        "HMD",
        "Controller",
        key["hash"],
        "Song",
        "Mapper",
        key["difficulty"],
    ]
    raw = struct.pack("<iBB", 0x442D3D69, 1, 0) + b"".join(string(x) for x in values)
    raw += (
        struct.pack("<i", score)
        + string(key["characteristic"])
        + string("DefaultEnvironment")
        + string("")
        + struct.pack("<fBffff", 1, 0, 1.7, 0, 0, 1)
    )
    for section in range(1, 6):
        raw += struct.pack("<BI", section, 0)
    return gzip.compress(raw)


def submit(api, data, replay=None):
    files = {"metadata": (None, json.dumps(data), "application/json")}
    if replay is not None:
        files["replay"] = ("../../untrusted.bsor.gz", replay, "application/gzip")
    return api.put(
        "/api/v1/qualifiers/challenges/" + data["challengeId"] + "/result",
        files=files,
        headers={"Idempotency-Key": data["clientResultId"]},
    )

import gzip
import json
from uuid import uuid4

from fastapi.testclient import TestClient

from mock_servers.score_manager.config import Settings
from mock_servers.score_manager.score_manager_server import create_app

from .conftest import FakeLeaderboardClient, authenticate, fixture_projections, metadata, reserve, result_files, valid_bsor


def submit(client, challenge, meta, replay=None, key=None):
    key = key or meta["clientResultId"]
    return client.put(f"/api/v1/qualifiers/challenges/{challenge}/result", headers={"Idempotency-Key": key}, files=result_files(meta, replay))


def test_metadata_only_invalid_result_and_duplicate_snapshot(server):
    client, *_ = server; authenticate(client)
    challenge = reserve(client).json()["challengeId"]
    meta = metadata(challenge)
    first = submit(client, challenge, meta); duplicate = submit(client, challenge, meta)
    assert first.status_code == 201 and duplicate.status_code == 200
    assert first.json() == duplicate.json()
    assert first.json()["replaySha256"] is None
    state = client.get("/__mock__/state").json()
    assert state["challengeCounts"]["submitted"] == 1 and state["budgets"][0]["usedAttempts"] == 1


def test_preflight_after_gameplay_entry_accepts_observed_play_count_one(server):
    client, *_ = server; authenticate(client)
    challenge = reserve(client).json()["challengeId"]
    meta = metadata(challenge, str(uuid4()))
    meta["scoreValidity"]["playInstanceCount"] = 1
    meta["timing"]["startedAtClient"] = "2030-01-01T00:00:01Z"
    accepted = submit(client, challenge, meta)
    assert accepted.status_code == 201, accepted.text


def test_ranked_clear_requires_and_validates_bsor(server):
    client, _, settings, *_ = server; authenticate(client)
    challenge = reserve(client).json()["challengeId"]
    meta = metadata(challenge, ranked=True, end_type="clear")
    assert submit(client, challenge, meta).status_code == 422
    accepted = submit(client, challenge, meta, valid_bsor())
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["replaySha256"]
    files = list(settings.replay_dir.glob("*.bsor"))
    assert len(files) == 1 and "unsafe" not in files[0].name


def test_bsor_identity_and_structure_errors_are_422(server):
    client, *_ = server; authenticate(client)
    challenge = reserve(client).json()["challengeId"]
    meta = metadata(challenge, ranked=True, end_type="clear")
    mismatch = submit(client, challenge, meta, valid_bsor(sid="someone-else"))
    assert mismatch.status_code == 422 and mismatch.json()["error"]["code"] == "replay_mismatch"
    malformed = submit(client, challenge, meta, gzip.compress(b"not-bsor"))
    assert malformed.status_code == 422 and malformed.json()["error"]["code"] == "replay_invalid"


def test_result_conflict_and_client_id_cross_challenge(server):
    client, *_ = server; authenticate(client)
    first_challenge = reserve(client, str(uuid4())).json()["challengeId"]
    result_id = str(uuid4()); first_meta = metadata(first_challenge, result_id)
    assert submit(client, first_challenge, first_meta).status_code == 201
    changed = dict(first_meta); changed["clientVersion"] = "Changed/1"
    assert submit(client, first_challenge, changed).status_code == 409
    second_challenge = reserve(client, str(uuid4())).json()["challengeId"]
    second_meta = metadata(second_challenge, result_id)
    conflict = submit(client, second_challenge, second_meta)
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "idempotency_conflict"


def test_csharp_production_encoder_all_sections_fixture_is_accepted(tmp_path):
    from mock_servers.score_manager.config import ROOT
    fixture_path = ROOT.parents[2] / "JBSLViewer.Qualifier.Tests" / "Fixtures" / "encoder-all-sections.bsor"
    raw = fixture_path.read_bytes()
    projections = fixture_projections()
    projection = projections[3023]
    projection["participants"] = [{"sid": "76561198000000001"}]
    projection["maps"][0]["hash"] = "A" * 40
    settings = Settings(database_path=tmp_path / "db.sqlite3", replay_dir=tmp_path / "replays", rate_limit_enabled=False, allow_insecure_loopback_cookie=True, stub_sid="76561198000000001")
    with TestClient(create_app(settings, FakeLeaderboardClient(projections))) as client:
        authenticate(client)
        map_key = {"hash": "A" * 40, "characteristic": "Standard", "difficulty": "ExpertPlus"}
        challenge = reserve(client, str(uuid4()), map_key).json()["challengeId"]
        meta = metadata(challenge, str(uuid4()), ranked=True, end_type="clear")
        meta["map"] = map_key
        accepted = submit(client, challenge, meta, gzip.compress(raw))
        assert accepted.status_code == 201, accepted.text
        assert accepted.json()["replaySha256"] == "57d9439340a4c3170de3d1ebfccfda0b65e15e5fe139f59b90e5d666f8f2d009"


def test_chunked_multipart_actual_read_limit_returns_413_without_state_change(server):
    client, app, settings, *_ = server; authenticate(client)
    challenge = reserve(client).json()["challengeId"]
    meta = metadata(challenge)
    boundary = "jbsl-stream-limit"
    prefix = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"metadata\"\r\nContent-Type: application/json\r\n\r\n"
        + json.dumps(meta) +
        f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"replay\"; filename=\"large.bsor.gz\"\r\nContent-Type: application/gzip\r\n\r\n"
    ).encode()
    oversized = b"X" * (settings.compressed_replay_limit + settings.metadata_limit + 1024 * 1024 + 1)
    def chunks():
        yield prefix
        for offset in range(0, len(oversized), 64 * 1024): yield oversized[offset:offset + 64 * 1024]
        yield f"\r\n--{boundary}--\r\n".encode()
    response = client.put(
        f"/api/v1/qualifiers/challenges/{challenge}/result",
        headers={"Idempotency-Key": meta["clientResultId"], "Content-Type": f"multipart/form-data; boundary={boundary}", "Transfer-Encoding": "chunked"},
        content=chunks(),
    )
    assert response.status_code == 413, response.text
    with app.state.db.connect() as connection:
        row = connection.execute("SELECT status FROM challenges WHERE id=?", (challenge,)).fetchone()
        assert row["status"] == "reserved"
        assert connection.execute("SELECT COUNT(*) FROM results WHERE challenge_id=?", (challenge,)).fetchone()[0] == 0

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import threading

from fastapi.testclient import TestClient

from mock_servers.score_manager.schemas import utc_text
from .conftest import authenticate, metadata, reserve, result_files, valid_bsor


def _set_deadline(app, challenge_id, value):
    db = app.state.db
    with db.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE challenges SET result_accept_until=? WHERE id=?", (utc_text(value), challenge_id))
        connection.commit()


def test_equal_deadline_profile_is_configurable(server):
    client, app, settings, _, clock = server; authenticate(client)
    challenge = reserve(client).json()["challengeId"]
    _set_deadline(app, challenge, clock.value)
    meta = metadata(challenge)
    accepted = client.put(f"/api/v1/qualifiers/challenges/{challenge}/result", headers={"Idempotency-Key": meta["clientResultId"]}, files=result_files(meta))
    assert settings.result_deadline_equal_is_accepted and accepted.status_code == 201


def test_expired_duplicate_returns_409_and_keeps_result(server):
    client, app, _, _, clock = server; authenticate(client)
    challenge = reserve(client).json()["challengeId"]
    meta = metadata(challenge)
    url = f"/api/v1/qualifiers/challenges/{challenge}/result"; headers = {"Idempotency-Key": meta["clientResultId"]}
    first = client.put(url, headers=headers, files=result_files(meta)); assert first.status_code == 201
    _set_deadline(app, challenge, clock.value - timedelta(seconds=1))
    expired = client.put(url, headers=headers, files=result_files(meta))
    assert expired.status_code == 409 and expired.json()["error"]["code"] == "result_acceptance_expired"
    with app.state.db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM results WHERE challenge_id=?", (challenge,)).fetchone()[0] == 1


def test_unsubmitted_expired_challenge_becomes_abandoned_without_refund(server):
    client, app, _, _, clock = server; authenticate(client)
    challenge = reserve(client).json()["challengeId"]
    _set_deadline(app, challenge, clock.value - timedelta(seconds=1))
    state = client.get("/__mock__/state").json()
    assert state["challengeCounts"]["abandoned"] == 1 and state["budgets"][0]["usedAttempts"] == 1


def test_result_validation_lock_prevents_midflight_abandon(server, monkeypatch):
    client, app, _, _, clock = server
    cookie = authenticate(client).cookies.get("jbslq_session")
    challenge = reserve(client).json()["challengeId"]
    meta = metadata(challenge, ranked=True, end_type="clear")
    entered = threading.Event(); release = threading.Event()
    from mock_servers.score_manager import score_manager_server
    original_decode = score_manager_server.decode_gzip
    def delayed_decode(*args):
        entered.set()
        assert release.wait(10)
        return original_decode(*args)
    monkeypatch.setattr(score_manager_server, "decode_gzip", delayed_decode)
    def send_result():
        with TestClient(app, cookies={"jbslq_session": cookie}) as other:
            return other.put(f"/api/v1/qualifiers/challenges/{challenge}/result", headers={"Idempotency-Key": meta["clientResultId"]}, files=result_files(meta, valid_bsor()))
    def read_state():
        with TestClient(app) as other: return other.get("/__mock__/state")
    with ThreadPoolExecutor(max_workers=2) as executor:
        result_future = executor.submit(send_result)
        assert entered.wait(10)
        clock.value += timedelta(days=3000)
        state_future = executor.submit(read_state)
        try:
            state_future.result(timeout=0.2)
            assert False, "state must wait for the in-flight result transaction"
        except TimeoutError:
            pass
        release.set()
        assert result_future.result(timeout=10).status_code == 201
        state = state_future.result(timeout=10).json()
    assert state["challengeCounts"]["submitted"] == 1
    assert state["challengeCounts"]["abandoned"] == 0

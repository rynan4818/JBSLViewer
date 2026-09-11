from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import multiprocessing
from uuid import uuid4

from fastapi.testclient import TestClient

from .conftest import authenticate, reserve


def _fixed_clock():
    return datetime(2030, 1, 1, tzinfo=timezone.utc)


def _process_reserve(db_path, replay_dir, key, start, output):
    from mock_servers.score_manager.config import Settings
    from mock_servers.score_manager.database import Database
    from mock_servers.score_manager.score_manager_server import _register_reservation, _reserve_transaction
    from mock_servers.score_manager.schemas import canonical_digest
    from mock_servers.score_manager.tests.conftest import MAP_A, FakeLeaderboardClient, fixture_projections
    settings = Settings(database_path=db_path, replay_dir=replay_dir, rate_limit_enabled=False, clock=_fixed_clock)
    db = Database(db_path)
    with db.connect() as connection:
        user = connection.execute("SELECT s.user_id,u.sid,s.auth_provider FROM sessions s JOIN users u ON u.id=s.user_id LIMIT 1").fetchone()
    body = {"schemaVersion": 1, "leagueId": 3023, "map": MAP_A, "clientVersion": "ProcessTest/1", "gameVersion": "1.29.1"}
    digest = canonical_digest(body)
    start.wait()
    try:
        _register_reservation(db, user["user_id"], key, digest, _fixed_clock())
        status, response = _reserve_transaction(db, FakeLeaderboardClient(fixture_projections()), settings, user, key, digest, body, _fixed_clock(), lambda: None)
        output.put((status, response))
    except Exception as exc:
        output.put(("error", repr(exc)))


def test_same_key_100_parallel_requests_make_one_challenge(server):
    client, app, *_ = server
    auth = authenticate(client)
    cookie = auth.cookies.get("jbslq_session")
    key = str(uuid4())

    def send(_):
        with TestClient(app, cookies={"jbslq_session": cookie}) as parallel_client:
            response = reserve(parallel_client, key)
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(send, range(100)))
    assert [status for status, _ in results].count(201) == 1
    assert [status for status, _ in results].count(200) == 99
    assert all(body == results[0][1] for _, body in results)
    state = client.get("/__mock__/state").json()
    assert state["budgets"][0]["usedAttempts"] == 1
    assert sum(state["challengeCounts"].values()) == 1
    assert state["requestCounts"]["jbslLeaderboardFetch"] == 1


def test_different_keys_never_exceed_limit(server):
    client, app, *_ = server
    cookie = authenticate(client).cookies.get("jbslq_session")
    keys = [str(uuid4()) for _ in range(12)]
    def send(key):
        with TestClient(app, cookies={"jbslq_session": cookie}) as c: return reserve(c, key).status_code
    with ThreadPoolExecutor(max_workers=12) as executor: statuses = list(executor.map(send, keys))
    assert statuses.count(201) == 3
    assert statuses.count(409) == 9
    assert client.get("/__mock__/state").json()["budgets"][0]["usedAttempts"] == 3


def test_same_key_different_payload_is_conflict(server):
    client, *_ = server; authenticate(client)
    key = str(uuid4())
    assert reserve(client, key).status_code == 201
    changed = {"hash": "89ABCDEF0123456789ABCDEF0123456789ABCDEF", "characteristic": "Standard", "difficulty": "Expert"}
    conflict = reserve(client, key, changed)
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "idempotency_conflict"


def test_same_key_is_safe_across_independent_processes(server):
    client, app, settings, *_ = server
    authenticate(client)
    context = multiprocessing.get_context("spawn")
    start = context.Event(); output = context.Queue(); key = str(uuid4())
    processes = [context.Process(target=_process_reserve, args=(settings.database_path, settings.replay_dir, key, start, output)) for _ in range(8)]
    for process in processes: process.start()
    start.set()
    results = [output.get(timeout=30) for _ in processes]
    for process in processes:
        process.join(30)
        assert process.exitcode == 0
    assert not [item for item in results if item[0] == "error"]
    assert [item[0] for item in results].count(201) == 1
    assert [item[0] for item in results].count(200) == 7
    assert all(item[1] == results[0][1] for item in results)
    assert client.get("/__mock__/state").json()["budgets"][0]["usedAttempts"] == 1

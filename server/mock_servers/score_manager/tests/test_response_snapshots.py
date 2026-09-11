from uuid import uuid4

from fastapi.testclient import TestClient

from mock_servers.score_manager.score_manager_server import create_app

from .conftest import authenticate, metadata, reserve, result_files


def test_reserve_snapshot_survives_other_consumption_and_limit_change(server):
    client, app, *_ = server; authenticate(client)
    key = str(uuid4()); first = reserve(client, key); assert first.status_code == 201
    assert reserve(client, str(uuid4())).status_code == 201
    with app.state.db.connect() as connection:
        connection.execute("BEGIN IMMEDIATE"); connection.execute("UPDATE attempt_budgets SET attempt_limit=100"); connection.commit()
    duplicate = reserve(client, key)
    assert duplicate.status_code == 200 and duplicate.json() == first.json()


def test_result_snapshot_survives_budget_change(server):
    client, app, *_ = server; authenticate(client)
    challenge = reserve(client).json()["challengeId"]; meta = metadata(challenge)
    url = f"/api/v1/qualifiers/challenges/{challenge}/result"; headers = {"Idempotency-Key": meta["clientResultId"]}
    first = client.put(url, headers=headers, files=result_files(meta)); assert first.status_code == 201
    with app.state.db.connect() as connection:
        connection.execute("BEGIN IMMEDIATE"); connection.execute("UPDATE attempt_budgets SET used_attempts=3"); connection.commit()
    duplicate = client.put(url, headers=headers, files=result_files(meta))
    assert duplicate.status_code == 200 and duplicate.json() == first.json()


def test_session_and_reserve_snapshot_survive_server_restart(server):
    client, _, settings, upstream, _ = server
    cookie = authenticate(client).cookies.get("jbslq_session")
    key = str(uuid4()); first = reserve(client, key); assert first.status_code == 201
    restarted_app = create_app(settings, upstream)
    with TestClient(restarted_app, cookies={"jbslq_session": cookie}) as restarted:
        assert restarted.get("/api/v1/auth/me").status_code == 200
        duplicate = reserve(restarted, key)
        assert duplicate.status_code == 200 and duplicate.json() == first.json()

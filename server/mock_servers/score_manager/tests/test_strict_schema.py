from uuid import uuid4

import pytest

from .conftest import MAP_A, authenticate, metadata, reserve, result_files


@pytest.mark.parametrize("bad_version", [True, 1.0, "1"])
def test_reserve_rejects_non_integer_schema_version(server, bad_version):
    client, *_ = server; authenticate(client)
    response = client.post("/api/v1/qualifiers/challenges", headers={"Idempotency-Key": str(uuid4())}, json={"schemaVersion": bad_version, "leagueId": 3023, "map": MAP_A, "clientVersion": "test", "gameVersion": "1.29.1"})
    assert response.status_code == 400


@pytest.mark.parametrize("bad_version", [True, 1.0, "1"])
def test_started_rejects_non_integer_schema_version(server, bad_version):
    client, *_ = server; authenticate(client)
    challenge = reserve(client, str(uuid4())).json()["challengeId"]
    response = client.post(f"/api/v1/qualifiers/challenges/{challenge}/started", json={"schemaVersion": bad_version, "actualMap": MAP_A, "gameMode": "Solo", "practice": False, "submissionAllowed": True, "startedAtClient": "2030-01-01T00:00:01Z"})
    assert response.status_code == 400


@pytest.mark.parametrize("bad_version", [True, 1.0, "1"])
def test_result_rejects_non_integer_schema_version(server, bad_version):
    client, app, *_ = server; authenticate(client)
    challenge = reserve(client, str(uuid4())).json()["challengeId"]
    meta = metadata(challenge, str(uuid4())); meta["schemaVersion"] = bad_version
    response = client.put(f"/api/v1/qualifiers/challenges/{challenge}/result", headers={"Idempotency-Key": meta["clientResultId"]}, files=result_files(meta))
    assert response.status_code == 400
    with app.state.db.connect() as connection:
        assert connection.execute("SELECT status FROM challenges WHERE id=?", (challenge,)).fetchone()["status"] == "reserved"

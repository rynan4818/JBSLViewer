from .conftest import MAP_A, authenticate, reserve


def test_started_is_idempotent_and_does_not_consume(server):
    client, *_ = server; authenticate(client)
    challenge = reserve(client).json()
    body = {"schemaVersion": 1, "actualMap": MAP_A, "gameMode": "Solo", "practice": False, "submissionAllowed": True, "startedAtClient": "2030-01-01T00:00:01Z"}
    first = client.post(f"/api/v1/qualifiers/challenges/{challenge['challengeId']}/started", json=body)
    second = client.post(f"/api/v1/qualifiers/challenges/{challenge['challengeId']}/started", json=body)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert client.get("/__mock__/state").json()["budgets"][0]["usedAttempts"] == 1


def test_started_rejects_practice_and_map_mismatch(server):
    client, *_ = server; authenticate(client)
    challenge = reserve(client).json()["challengeId"]
    practice = {"schemaVersion": 1, "actualMap": MAP_A, "gameMode": "Solo", "practice": True, "submissionAllowed": True, "startedAtClient": None}
    assert client.post(f"/api/v1/qualifiers/challenges/{challenge}/started", json=practice).status_code == 422


import pytest
from jsonschema import Draft202012Validator

from jbsl_score.errors import ApiProblem
from jbsl_score.upstream import Identity

from .conftest import MAP, SID, bsor, login, login_admin, metadata, reserve, submit
from .test_rules import policy


def scored(api, score=115, *, sid=SID, key=None, league=3023, end="clear"):
    key = key or MAP
    reservation = reserve(api, map_key=key, league=league)
    assert reservation.status_code == 201, reservation.text
    data = metadata(reservation.json()["challengeId"], end, score=score)
    data["map"] = key
    response = submit(api, data, bsor(sid=sid, score=score, key=key))
    assert response.status_code == 201, response.text
    return response.json()["submissionId"]


def board(admin, league=3023):
    response = admin.get("/admin/api/rankings", params={"leagueId": league})
    assert response.status_code == 200, response.text
    doc = admin.get("/admin/openapi.json").json()
    Draft202012Validator({"$ref": "#/components/schemas/AdminRankings", "components": doc["components"]}).validate(response.json())
    return response.json()


def test_highest_per_user_ties_and_integration_agree(server, monkeypatch):
    api, admin, service, upstream, clock, token = server
    upstream.data["maps"][0]["qualifier_attempt_limit"] = 10
    login(api)
    scored(api, 90)
    clock.now += 1
    best = scored(api, 115)
    clock.now += 1
    scored(api, 115)
    login(api, other=True)
    tied = scored(api, 115, sid="76561198000000001", end="fail")
    third_sid = "76561198000000002"
    upstream.data["participants"].append({"sid": third_sid})
    monkeypatch.setattr(service.verifier, "verify", lambda *args: Identity(third_sid, "Third Player", "steamTicket"))
    login(api)
    third = scored(api, 80, sid=third_sid)
    login_admin(admin)
    result = board(admin)
    assert [(r["rank"], r["submissionId"], r["modifiedScore"]) for r in result["items"]] == [
        (1, best, 115), (1, tied, 115), (3, third, 80)
    ]
    assert result["items"][-1]["displayName"] == "Third Player"
    assert [r["remainingAttempts"] for r in result["items"]] == [7, 9, 9]
    assert result["maps"][0]["attemptLimit"] == 10
    assert result["maps"][0]["songDurationSeconds"] == 180
    integrated = api.get("/integration/v1/leagues/3023/leaderboard", headers={"Authorization": "Bearer " + token})
    admin_fields = {"displayName", "remainingAttempts"}
    assert [{k: v for k, v in r.items() if k not in admin_fields} for r in result["items"]] == integrated.json()["items"]


def test_cancel_falls_back_restore_and_refund_keep_correct_submission(server):
    api, admin, _, _, clock, _ = server
    login(api)
    fallback = scored(api, 95)
    clock.now += 1
    best = scored(api, 110)
    invalid = submit(api, metadata(reserve(api).json()["challengeId"]))
    assert invalid.status_code == 201
    login_admin(admin)
    selected = board(admin)["items"][0]
    assert selected["submissionId"] == best
    assert selected["remainingAttempts"] == 0
    details = admin.get(f"/admin/api/submissions/{best}").json()
    assert details["challengeId"] == selected["challengeId"]
    path = f"/admin/api/submissions/{best}/moderate"
    for version, action, expected in ((0, "cancel", fallback), (1, "restore", best)):
        response = admin.post(path, json={"version": version, "action": action, "reason": "ランキング確認"})
        assert response.status_code == 200
        items = board(admin)["items"]
        assert len(items) == 1 and items[0]["submissionId"] == expected
        assert items[0]["rank"] == 1
        assert items[0]["remainingAttempts"] == 0
    response = admin.post(f"/admin/api/challenges/{selected['challengeId']}/refund", json={"reason": "再挑戦"})
    assert response.status_code == 200
    after = board(admin)["items"][0]
    assert after["submissionId"] == best and after["attemptRefunded"] is True
    attempts = admin.get(f"/admin/api/users/{SID}/attempts").json()["items"][0]
    assert attempts["usedAttempts"] == 2 and attempts["refundedAttempts"] == 1
    assert after["remainingAttempts"] == attempts["remainingAttempts"] == 1


def test_leagues_hashes_characteristics_difficulties_are_independent(server):
    api, admin, _, upstream, _, _ = server
    keys = [MAP, {**MAP, "difficulty": "Expert"}, {**MAP, "characteristic": "OneSaber"}, {**MAP, "hash": "A" * 40}]
    original_map = upstream.data["maps"][0]
    upstream.data["maps"] = [
        {**original_map, **key, "title": f"譜面 {i}", "qualifier_attempt_limit": i + 2, "song_duration_seconds": 30.5 + i}
        for i, key in enumerate(keys)
    ]
    login(api)
    expected = {scored(api, 30 + i, key=key) for i, key in enumerate(keys)}
    upstream.data["league_id"] = 4023
    upstream.data["league_title"] = "別リーグ"
    upstream.data["maps"][0]["qualifier_attempt_limit"] = 5
    other = scored(api, 110, league=4023)
    login_admin(admin)
    result = board(admin)
    assert {r["submissionId"] for r in result["items"]} == expected
    assert all(r["rank"] == 1 for r in result["items"])
    assert len(result["maps"]) == 4
    for i, key in enumerate(keys):
        item = next(r for r in result["items"] if r["map"] == key)
        chart = next(m for m in result["maps"] if all(m[k] == v for k, v in key.items()))
        assert item["remainingAttempts"] == i + 1
        assert chart["attemptLimit"] == i + 2 and chart["songDurationSeconds"] == 30.5 + i
    assert [r["leagueId"] for r in result["leagues"]] == [3023, 4023]
    assert result["leagues"][1]["title"] == "別リーグ"
    assert board(admin, 4023)["items"][0]["submissionId"] == other
    assert board(admin, 4023)["items"][0]["remainingAttempts"] == 4


def test_empty_and_historical_maps_are_available_without_upstream_or_writes(server):
    api, admin, service, upstream, _, _ = server
    login_admin(admin)
    empty = admin.get("/admin/api/rankings").json()
    assert empty == {"leagues": [], "leagueId": None, "maps": [], "items": []}
    doc = admin.get("/admin/openapi.json").json()
    Draft202012Validator({"$ref": "#/components/schemas/AdminRankings", "components": doc["components"]}).validate(empty)
    assert admin.post("/admin/api/leagues/3023/refresh").status_code == 200
    assert board(admin)["maps"][0]["title"] == "Contract song"
    assert board(admin)["items"] == []
    login(api)
    best = scored(api)
    upstream.data["maps"][0].update(hash="B" * 40, title="未提出の新譜面")
    assert admin.post("/admin/api/leagues/3023/refresh").status_code == 200
    upstream.error = ApiProblem(503, "upstream_unavailable", "offline")
    calls = upstream.calls
    with service.db.read() as c:
        before = {table: [tuple(r) for r in c.execute("SELECT * FROM " + table)]
                  for table in ("users", "sessions", "budgets", "results", "challenges", "changes", "audit", "league_cache")}
    result = board(admin)
    assert {m["title"] for m in result["maps"]} == {"未提出の新譜面", MAP["hash"]}
    assert result["items"][0]["submissionId"] == best
    assert result["items"][0]["remainingAttempts"] is None
    historical = next(m for m in result["maps"] if m["hash"] == MAP["hash"])
    assert historical["attemptLimit"] is None and historical["songDurationSeconds"] is None
    with service.db.read() as c:
        for table, expected in before.items():
            assert [tuple(r) for r in c.execute("SELECT * FROM " + table)] == expected
    assert upstream.calls == calls
    with service.db.transaction() as c:
        c.execute("DELETE FROM league_cache")
    result = board(admin)
    assert result["leagues"] == [{"leagueId": 3023, "title": "League 3023"}]
    assert result["items"][0]["submissionId"] == best
    assert result["items"][0]["remainingAttempts"] is None


def test_remaining_uses_current_budget_and_limit_even_after_best_score(server):
    api, admin, _, upstream, _, _ = server
    login(api)
    best = scored(api)
    login_admin(admin)
    assert board(admin)["items"][0]["remainingAttempts"] == 2
    pending = reserve(api)
    assert pending.status_code == 201
    assert board(admin)["items"][0]["remainingAttempts"] == 1
    assert submit(api, metadata(pending.json()["challengeId"], "quit")).status_code == 201
    assert reserve(api).status_code == 201
    for limit, expected in ((3, 0), (1, 0), (6, 3)):
        upstream.data["maps"][0]["qualifier_attempt_limit"] = limit
        upstream.data["maps"][0]["song_duration_seconds"] = None
        assert admin.post("/admin/api/leagues/3023/refresh").status_code == 200
        result = board(admin)
        assert result["maps"][0]["attemptLimit"] == limit
        assert result["maps"][0]["songDurationSeconds"] is None
        assert result["items"][0]["submissionId"] == best
        attempts = admin.get(f"/admin/api/users/{SID}/attempts").json()["items"][0]
        assert result["items"][0]["remainingAttempts"] == attempts["remainingAttempts"] == expected
    upstream.data["qualifier"]["enabled"] = False
    upstream.data["maps"][0]["qualifier_attempt_limit"] = None
    assert admin.post("/admin/api/leagues/3023/refresh").status_code == 200
    result = board(admin)
    assert result["maps"][0]["attemptLimit"] is None
    assert result["items"][0]["remainingAttempts"] is None


def test_ranking_remaining_reflects_automatic_refund_once(server):
    api, admin, service, _, _, _ = server
    policy(service, refund_conditions=["quit"])
    login(api)
    scored(api)
    login_admin(admin)
    pending = reserve(api).json()
    assert board(admin)["items"][0]["remainingAttempts"] == 1
    data = metadata(pending["challengeId"], "quit")
    assert submit(api, data).status_code == 201
    assert board(admin)["items"][0]["remainingAttempts"] == 2
    assert submit(api, data).status_code == 200
    assert board(admin)["items"][0]["remainingAttempts"] == 2


@pytest.mark.parametrize("league", ["0", "-1", "1.5", "abc", "１", "2147483648", "", "1 OR 1=1"])
def test_invalid_league_is_rejected(server, league):
    _, admin, *_ = server
    login_admin(admin)
    assert admin.get("/admin/api/rankings", params={"leagueId": league}).status_code == 400


def test_unknown_league_is_rejected(server):
    _, admin, *_ = server
    login_admin(admin)
    assert admin.get("/admin/api/rankings", params={"leagueId": 9999}).status_code == 404

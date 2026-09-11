import pytest
from fastapi.testclient import TestClient

from jbsl_score.errors import ApiProblem
from jbsl_score.upstream import Identity

from .conftest import MAP, SID, login, login_admin, metadata, reserve, submit
from .test_rankings import scored

PUBLIC = "/admin/api/public/rankings"
ITEM_FIELDS = {
    "rank", "sid", "displayName", "map", "modifiedScore", "accuracyPercent",
    "remainingAttempts", "receivedAt", "endType", "replay",
}


def snapshot(service):
    with service.db.read() as c:
        return list(c.iterdump())


@pytest.mark.parametrize("cookie", [None, "expired-admin-token"])
def test_public_page_assets_and_api_need_no_session(server, cookie):
    api, admin, service, *_ = server
    if cookie:
        admin.cookies.set("jbslq_admin", cookie)
    before = snapshot(service)
    for path in ("/admin/rankings/", "/admin/static/rankings.html", "/admin/static/rankings.js", PUBLIC):
        response = admin.get(path)
        assert response.status_code == 200
        assert "set-cookie" not in response.headers
        assert "no-store" in response.headers["cache-control"]
        assert "script-src 'self'" in response.headers["content-security-policy"]
    assert admin.get(PUBLIC).json() == {"leagues": [], "leagueId": None, "maps": [], "items": []}
    assert snapshot(service) == before
    assert admin.get("/admin/rankings", follow_redirects=False).status_code == 307
    assert api.get(PUBLIC).status_code == 404
    assert api.get("/admin/rankings/").status_code == 404
    assert admin.get("/admin/api/me").status_code == 401


def test_public_data_is_limited_matches_admin_and_is_read_only(server, monkeypatch):
    api, admin, service, upstream, clock, _ = server
    upstream.data["maps"][0]["qualifier_attempt_limit"] = 10
    login(api)
    scored(api, 90)
    clock.now += 1
    scored(api, 115)
    login(api, other=True)
    scored(api, 115, sid="76561198000000001", end="fail")
    third_sid = "76561198000000002"
    upstream.data["participants"].append({"sid": third_sid})
    name = "日本語 <img src=x onerror=alert(1)>"
    monkeypatch.setattr(service.verifier, "verify", lambda *args: Identity(third_sid, name, "steamTicket"))
    login(api)
    scored(api, 80, sid=third_sid)
    assert submit(api, metadata(reserve(api).json()["challengeId"])).status_code == 201
    upstream.error = ApiProblem(503, "upstream_unavailable", "offline")
    calls = upstream.calls
    before = snapshot(service)
    response = admin.get(PUBLIC)
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"leagues", "leagueId", "maps", "items"}
    assert data["leagueId"] == 3023
    assert [(r["rank"], r["modifiedScore"], r["remainingAttempts"]) for r in data["items"]] == [
        (1, 115, 8), (1, 115, 9), (3, 80, 8),
    ]
    assert data["items"][2]["displayName"] == name
    assert all(set(item) == ITEM_FIELDS and set(item["map"]) == set(MAP) for item in data["items"])
    assert all(set(item["replay"]) == {"downloadUrl", "beatleaderUrl", "arcviewerUrl"} for item in data["items"])
    assert all(set(league) == {"leagueId", "title"} for league in data["leagues"])
    assert all(set(chart) == {*MAP, "title", "attemptLimit", "songDurationSeconds"} for chart in data["maps"])
    assert snapshot(service) == before
    assert upstream.calls == calls
    assert not admin.cookies and "set-cookie" not in response.headers
    login_admin(admin)
    expected = admin.get("/admin/api/rankings").json()
    assert [{key: value for key, value in item.items() if key != "replay"} for item in data["items"]] == [
        {key: item[key] for key in ITEM_FIELDS - {"replay"}} for item in expected["items"]
    ]
    assert {key: value for key, value in data.items() if key != "items"} == {
        key: value for key, value in expected.items() if key != "items"
    }


def test_public_scores_follow_moderation_and_current_remaining_attempts(server):
    api, admin, service, *_ = server
    login(api)
    scored(api, 90)
    best = scored(api, 115)
    login(api, other=True)
    scored(api, 110, sid="76561198000000001")
    login_admin(admin)
    challenge = admin.get(f"/admin/api/submissions/{best}").json()["challengeId"]
    with TestClient(admin.app, base_url=service.config.admin_public_url) as guest:
        for version, action, expected_score, expected_rank in ((0, "cancel", 90, 2), (1, "restore", 115, 1)):
            assert admin.post(
                f"/admin/api/submissions/{best}/moderate",
                json={"action": action, "version": version, "reason": "公開しない確認理由"},
            ).status_code == 200
            response = guest.get(PUBLIC)
            row = next(item for item in response.json()["items"] if item["sid"] == SID)
            assert (row["modifiedScore"], row["rank"], row["remainingAttempts"]) == (expected_score, expected_rank, 1)
            assert "公開しない確認理由" not in response.text
        assert admin.post(f"/admin/api/challenges/{challenge}/refund", json={"reason": "公開しない返却理由"}).status_code == 200
        row = next(item for item in guest.get(PUBLIC).json()["items"] if item["sid"] == SID)
        assert (row["modifiedScore"], row["rank"], row["remainingAttempts"]) == (115, 1, 2)
        assert not guest.cookies


def test_public_league_selection_and_historical_charts(server):
    api, admin, service, upstream, *_ = server
    login(api)
    scored(api, 90)
    upstream.data["league_id"] = 4023
    upstream.data["league_title"] = "別リーグ"
    upstream.data["maps"][0]["song_duration_seconds"] = None
    scored(api, 110, league=4023)
    result = admin.get(PUBLIC, params={"leagueId": 4023}).json()
    assert [entry["leagueId"] for entry in result["leagues"]] == [3023, 4023]
    assert result["leagueId"] == 4023 and result["items"][0]["modifiedScore"] == 110
    assert result["maps"][0]["songDurationSeconds"] is None
    with service.db.transaction() as c:
        c.execute("DELETE FROM league_cache WHERE league_id=3023")
    historical = admin.get(PUBLIC).json()
    assert historical["leagueId"] == 3023
    assert historical["items"][0]["modifiedScore"] == 90
    assert historical["items"][0]["remainingAttempts"] is None
    assert historical["maps"] == [{**MAP, "title": MAP["hash"], "attemptLimit": None, "songDurationSeconds": None}]


@pytest.mark.parametrize("league", ["0", "-1", "1.5", "abc", "１", "2147483648", "", "1 OR 1=1"])
def test_public_invalid_league_is_rejected(server, league):
    assert server[1].get(PUBLIC, params={"leagueId": league}).status_code == 400


def test_public_unknown_league_and_mutations_are_rejected(server):
    admin = server[1]
    assert admin.get(PUBLIC, params={"leagueId": 9999}).status_code == 404
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert admin.request(method, PUBLIC, json={}).status_code == 405


def test_public_view_does_not_authorize_management(server):
    api, admin, *_ = server
    login(api)
    best = scored(api)
    assert admin.get("/admin/rankings/").status_code == 200
    assert admin.get(PUBLIC).status_code == 200
    for path in (
        "/admin/api/me", "/admin/api/rankings", "/admin/api/state", "/admin/api/settings",
        "/admin/api/users", "/admin/api/challenges", "/admin/api/audit",
        f"/admin/api/submissions/{best}", f"/admin/api/submissions/{best}/replay", f"/admin/api/users/{SID}/attempts",
    ):
        assert admin.get(path).status_code == 401
    for path, body in (
        (f"/admin/api/submissions/{best}/moderate", {"action": "cancel", "version": 0, "reason": "拒否確認"}),
        (f"/admin/api/submissions/{best}/replay-viewer", {"viewer": "beatleader"}),
    ):
        assert admin.post(path, json=body).status_code == 401
    assert not admin.cookies

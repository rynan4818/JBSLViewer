import json

import httpx
import pytest

from jbsl_score.database import dumps
from jbsl_score.errors import ApiProblem
from jbsl_score.security import Security
from jbsl_score.service import Service
from jbsl_score.upstream import Identity, LeaderboardClient

from .conftest import MAP, SID, login, login_admin
from .test_rankings import board, scored

OTHER_SID = "76561198000000001"


@pytest.fixture
def web(server, monkeypatch):
    """Run the production HTTP parser while isolating the external WEB and ticket provider."""
    _, _, service, upstream, _, _ = server
    calls = []

    def handle(request):
        calls.append(request)
        assert request.method == "GET"
        assert request.url.path == f"/leaderboard/api/{upstream.data['league_id']}"
        if upstream.error:
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(200, content=json.dumps(upstream.data).encode(), headers={"Content-Type": "application/json"})

    monkeypatch.setattr(service, "upstream", LeaderboardClient(service.config, httpx.MockTransport(handle)))
    verify = service.verifier.verify

    def sid_identity(ticket, provider):
        identity = verify(ticket, provider)
        return Identity(identity.sid, identity.sid, provider)

    monkeypatch.setattr(service.verifier, "verify", sid_identity)
    return calls


def test_http_names_are_display_metadata_and_do_not_grant_participation(server, web, monkeypatch):
    api, _, service, upstream, _, _ = server
    outsider = "99999999999999999"
    upstream.data["total_rank"] = [{"sid": SID, "name": "  日本語 <img src=x onerror=alert(1)>  "}]
    upstream.data["maps"][0]["scores"] = [
        {"sid": SID, "name": "Lower priority"},
        {"sid": OTHER_SID, "name": "Map player"},
        {"sid": outsider, "name": "Outside player"},
    ]
    result, _ = service.fetch_projection(3023)
    assert result["player_names"] == {
        SID: "日本語 <img src=x onerror=alert(1)>", OTHER_SID: "Map player", outsider: "Outside player"
    }
    assert result["participants"] == upstream.data["participants"]
    assert "total_rank" not in result and "scores" not in result["maps"][0]
    with service.db.read() as c:
        stored = json.loads(c.execute("SELECT projection_json FROM league_cache").fetchone()[0])
        assert stored == result
        assert c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    monkeypatch.setattr(service.verifier, "verify", lambda *args: Identity(outsider, outsider, "steamTicket"))
    assert login(api).json()["user"]["displayName"] == "Outside player"
    status = api.get("/api/v1/qualifiers/status", params={"leagueId": 3023, **MAP})
    assert status.status_code == 200
    assert status.json()["isParticipant"] is False and status.json()["eligible"] is False


@pytest.mark.parametrize("name", [None, 17, {}, [], "", "  ", "x" * 201, "a\x00b", "a\ud800b", SID])
def test_invalid_optional_name_falls_back_to_map_scores(server, web, name):
    _, _, service, upstream, _, _ = server
    upstream.data["total_rank"] = [None, {"sid": SID, "name": name}, {"sid": 123, "name": "Wrong ID type"}]
    upstream.data["maps"][0]["scores"] = [{"sid": SID, "name": "Map fallback"}]
    assert service.upstream.get(3023)["player_names"] == {SID: "Map fallback"}


@pytest.mark.parametrize("ranking", [None, {}, "invalid", 1])
def test_optional_ranking_structure_can_be_absent_or_invalid(server, web, ranking):
    _, _, service, upstream, _, _ = server
    upstream.data["total_rank"] = ranking
    upstream.data["maps"][0]["scores"] = ranking
    upstream.data["player_names"] = {SID: "Not a supported upstream field"}
    assert service.upstream.get(3023)["player_names"] == {}


@pytest.mark.parametrize("source", ["total_rank", "participants"])
def test_refresh_fills_existing_user_and_name_survives_offline_relogin_and_restart(server, web, source):
    api, admin, service, upstream, clock, _ = server
    assert login(api).json()["user"]["displayName"] == SID
    scored(api)
    login_admin(admin)
    assert board(admin)["items"][0]["displayName"] == SID
    upstream.data[source] = [{"sid": SID, "name": "星空プレイヤー"}]
    clock.now += 1
    assert admin.post("/admin/api/leagues/3023/refresh").status_code == 200
    assert board(admin)["items"][0]["displayName"] == "星空プレイヤー"
    assert api.get("/api/v1/auth/me").json()["user"]["displayName"] == "星空プレイヤー"
    users = admin.get("/admin/api/users", params={"q": "星空", "limit": 1}).json()
    assert [(u["sid"], u["displayName"]) for u in users["items"]] == [(SID, "星空プレイヤー")]
    assert users["nextCursor"] is None
    upstream.error = ApiProblem(503, "upstream_unavailable", "offline")
    assert admin.post("/admin/api/leagues/3023/refresh").status_code == 503
    calls = len(web)
    assert login(api).json()["user"]["displayName"] == "星空プレイヤー"
    restarted = Service(service.config, service.upstream, service.verifier, clock)
    _, response = Security(restarted).login_player("mock-ticket", "steamTicket")
    assert response["user"]["displayName"] == "星空プレイヤー"
    assert board(admin)["items"][0]["displayName"] == "星空プレイヤー"
    assert len(web) == calls


@pytest.mark.parametrize("source", ["total_rank", "participants"])
def test_first_login_uses_newest_cached_name_and_search_paginates(server, web, source):
    api, admin, service, upstream, clock, _ = server
    upstream.data[source] = [{"sid": SID, "name": "以前の名前"}]
    service.fetch_projection(3023)
    clock.now += 1
    upstream.data["league_id"] = 4023
    upstream.data[source] = [
        {"sid": SID, "name": "共有の名前 一人目"}, {"sid": OTHER_SID, "name": "共有の名前 二人目"}
    ]
    service.fetch_projection(4023)
    calls = len(web)
    assert login(api).json()["user"]["displayName"] == "共有の名前 一人目"
    assert login(api, other=True).json()["user"]["displayName"] == "共有の名前 二人目"
    login_admin(admin)
    first = admin.get("/admin/api/users", params={"q": "共有の名前", "limit": 1}).json()
    assert first["items"][0]["sid"] == SID and first["nextCursor"] == SID
    second = admin.get("/admin/api/users", params={"q": "共有の名前", "limit": 1, "after": first["nextCursor"]}).json()
    assert second["items"][0]["sid"] == OTHER_SID and second["nextCursor"] is None
    assert len(web) == calls


@pytest.mark.parametrize("source", ["total_rank", "participants"])
def test_existing_provider_name_is_not_replaced_by_web_or_sid_relogin(server, web, monkeypatch, source):
    api, _, service, upstream, _, _ = server
    monkeypatch.setattr(service.verifier, "verify", lambda *args: Identity(SID, "Provider Name", "steamTicket"))
    assert login(api).json()["user"]["displayName"] == "Provider Name"
    upstream.data[source] = [{"sid": SID, "name": "WEB Name"}]
    service.fetch_projection(3023)
    assert api.get("/api/v1/auth/me").json()["user"]["displayName"] == "Provider Name"
    monkeypatch.setattr(service.verifier, "verify", lambda *args: Identity(SID, SID, "steamTicket"))
    assert login(api).json()["user"]["displayName"] == "Provider Name"


@pytest.mark.parametrize("cache", ["absent", "legacy", "different_sid"])
def test_missing_name_or_legacy_cache_keeps_exact_sid(server, web, cache):
    api, _, service, upstream, clock, _ = server
    if cache == "legacy":
        with service.db.transaction() as c:
            c.execute("INSERT INTO league_cache VALUES(?,?,?,NULL)", (3023, dumps(upstream.data), clock()))
    elif cache == "different_sid":
        upstream.data["total_rank"] = [{"sid": "0" + SID, "name": "Different SID"}]
        service.fetch_projection(3023)
    calls = len(web)
    assert login(api).json()["user"] == {"sid": SID, "displayName": SID}
    assert len(web) == calls


def test_participant_names_take_priority_over_rankings_without_affecting_eligibility(server, web):
    api, _, service, upstream, _, _ = server
    upstream.data["participants"][0]["name"] = "  参加者の名前  "
    upstream.data["total_rank"] = [{"sid": SID, "name": "Ranking fallback"}]
    upstream.data["maps"][0]["scores"] = [{"sid": SID, "name": "Map fallback"}]
    projection, _ = service.fetch_projection(3023)
    assert projection["player_names"][SID] == "参加者の名前"
    assert projection["participants"] == [{"sid": SID}, {"sid": OTHER_SID}]
    assert login(api).json()["user"]["displayName"] == "参加者の名前"
    status = api.get("/api/v1/qualifiers/status", params={"leagueId": 3023, **MAP})
    assert status.json()["isParticipant"] is True and status.json()["eligible"] is True


@pytest.mark.parametrize("name", [None, 17, {}, [], "", "  ", "x" * 201, "a\x00b", "a\ud800b", SID])
def test_invalid_participant_name_is_optional_and_uses_ranking_fallback(server, web, name):
    _, _, service, upstream, _, _ = server
    upstream.data["participants"][0]["name"] = name
    upstream.data["total_rank"] = [{"sid": SID, "name": "Ranking fallback"}]
    result, _ = service.fetch_projection(3023)
    assert result["player_names"] == {SID: "Ranking fallback"}
    assert result["participants"] == [{"sid": SID}, {"sid": OTHER_SID}]

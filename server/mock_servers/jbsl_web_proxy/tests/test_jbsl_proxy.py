import copy
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from mock_servers.jbsl_web_proxy.config import ROOT, Settings
from mock_servers.jbsl_web_proxy.jbsl_web_proxy_server import FixtureStore, create_app, merge_leaderboard


def test_proxy_preserves_baseline_and_adds_contract_fields():
    settings = Settings()
    with TestClient(create_app(settings)) as client:
        response = client.get("/leaderboard/api/3023")
        assert response.status_code == 200
        body = response.json()
        assert body["maps"][0]["scores"][0]["miss"] == 0
        assert body["maps"][0]["lid"] == "1001"
        assert body["maps"][0]["characteristic"] == "Standard"
        assert body["participants"] == [{"sid": "76561198000000000", "name": "Test Player"}]
        assert response.headers["x-jbsl-mock-server"] == "true"
        assert client.get("/__mock__/state").json()["requestCounts"]["byLeague"]["3023"] == 1


def test_proxy_unknown_league_without_saved_upstream_is_404():
    with TestClient(create_app(Settings())) as client:
        response = client.get("/leaderboard/api/9999")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "league_not_found"


def test_proxy_unconfigured_saved_json_is_relayed_byte_for_byte(tmp_path):
    content = b'{\n  "league_id": 9999, "maps": [], "custom": 1.00\n}\n'
    (tmp_path / "leaderboard_9999.json").write_bytes(content)
    with TestClient(create_app(Settings(offline_upstream_dir=tmp_path))) as client:
        response = client.get("/leaderboard/api/9999")
        assert response.status_code == 200 and response.content == content


@pytest.mark.parametrize("content", [b'{"league_id":9999,"extra": 1.00}', b'[{"new":"shape"}]', b'null'])
def test_proxy_unconfigured_live_json_skips_fixture_projection(monkeypatch, content):
    client_class = httpx.AsyncClient
    def upstream(request):
        assert request.url == "https://jbsl-web.herokuapp.com/leaderboard/api/9999"
        return httpx.Response(200, content=content)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_class(transport=httpx.MockTransport(upstream), **kwargs))
    with TestClient(create_app(Settings(offline_upstream_dir=None))) as client:
        response = client.get("/leaderboard/api/9999")
        assert response.status_code == 200 and response.content == content


def test_ranking_participants_default_on_deduplicated_and_never_mutate_inputs():
    upstream = json.loads((ROOT / "fixtures/upstream/leaderboard_3023.json").read_text(encoding="utf-8"))
    fixture = FixtureStore(Settings().fixture_path).get(3023)
    manual = fixture["participants"][0]["sid"]
    upstream["total_rank"].extend([{"sid": "9007199254740993"}, {"sid": manual}, {"sid": "9007199254740993"}])
    upstream["maps"][1]["scores"] = [{"sid": "map-only"}, {"sid": "9007199254740993"}, {"sid": 123}, {"sid": " "}, None]
    originals = copy.deepcopy((upstream, fixture))
    merged = merge_leaderboard(upstream, fixture, 3023)
    assert merged["participants"] == [{"sid": manual, "name": "Test Player"},
                                      {"sid": "9007199254740993", "name": "9007199254740993"},
                                      {"sid": "map-only", "name": "map-only"}]
    assert (upstream, fixture) == originals
    assert merged["total_rank"] == upstream["total_rank"] and merged["maps"][1]["scores"] == upstream["maps"][1]["scores"]
    fixture["auto_add_ranking_sids"] = False
    assert merge_leaderboard(upstream, fixture, 3023)["participants"] == [{"sid": manual, "name": "Test Player"}]


def test_proxy_rejects_non_decimal_and_non_loopback_host():
    with TestClient(create_app(Settings())) as client:
        assert client.get("/leaderboard/api/0").status_code == 400
        assert client.get("/leaderboard/api/3023", headers={"host": "public.example"}).status_code == 403


def test_standalone_proxy_allows_only_configured_public_domain():
    with TestClient(create_app(Settings(public_url="https://relay.example/"))) as client:
        response = client.get("/leaderboard/api/3023", headers={"Host": "relay.example:443"})
        assert response.status_code == 200 and response.json()["league_id"] == 3023
        assert client.get("/docs", headers={"Host": "unconfigured.example"}).status_code == 403


def test_proxy_fault_profiles_are_explicit_in_state():
    unavailable = Settings(proxy_fault_profile="upstream_unavailable")
    with TestClient(create_app(unavailable)) as client:
        assert client.get("/leaderboard/api/3023").status_code == 503
        assert client.get("/__mock__/state").json()["faultProfile"] == "upstream_unavailable"
    invalid = Settings(proxy_fault_profile="upstream_invalid")
    with TestClient(create_app(invalid)) as client:
        response = client.get("/leaderboard/api/3023")
        assert response.status_code == 200 and response.text == "{invalid"


def test_openapi_identifies_test_only_server():
    with TestClient(create_app(Settings())) as client:
        schema = client.get("/openapi.json").json()
        assert "TEST ONLY" in schema["info"]["title"]

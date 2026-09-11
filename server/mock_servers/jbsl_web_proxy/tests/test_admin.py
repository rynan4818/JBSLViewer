import asyncio
import copy
import json
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from mock_servers.jbsl_web_proxy.admin_server import make_apps
from mock_servers.jbsl_web_proxy.config import ROOT
from mock_servers.jbsl_web_proxy.control import Behavior, Control, TrafficLog


HEADERS = {"X-JBSL-Admin": "1"}
ADMIN_USER = "relay-admin"
ADMIN_PASSWORD = "test-only-password-2026"
ACTIVE = [{"id": 7001, "name": "実API形式テスト <script>", "isLive": True, "isOpen": True,
           "end": "2035-09-30T15:00:00Z", "playlist_id": 9001}]


class PublicFixture:
    def __init__(self):
        self.requests = []
        self.fail = False
        self.invalid = False
        self.songs_fail = False
        self.beatsaver_requests = []
        self.beatsaver_status = 200
        self.beatsaver_duration = 195
        self.scoresaber_requests = []
        self.scoresaber_profiles = {}
        self.raw_board = None
        self.board = json.loads((ROOT / "fixtures/upstream/leaderboard_3023.json").read_text(encoding="utf-8"))
        self.board.update(league_id=7001, league_title=ACTIVE[0]["name"])

    def __call__(self, request):
        assert request.method == "GET"
        assert "cookie" not in request.headers and "authorization" not in request.headers
        if request.url.host == "scoresaber.com":
            self.scoresaber_requests.append(request.url.path)
            profile = self.scoresaber_profiles.get(request.url.path.rsplit("/", 1)[-1])
            return httpx.Response(200, json=profile) if profile else httpx.Response(404)
        if request.url.host == "api.beatsaver.com":
            self.beatsaver_requests.append(request.url.path)
            return httpx.Response(self.beatsaver_status, text=json.dumps({"metadata": {"duration": self.beatsaver_duration},
                                                                        "versions": [{"diffs": [{"seconds": 189.438}]}]}))
        assert request.url.host == "jbsl-web.herokuapp.com"
        self.requests.append(request.url.path)
        if self.fail:
            return httpx.Response(503)
        if self.invalid:
            return httpx.Response(200, text="broken-json")
        if request.url.path == "/api/active_league":
            return httpx.Response(200, json=ACTIVE)
        if request.url.path == "/leaderboard/api/7001":
            if self.raw_board is not None:
                return httpx.Response(200, content=self.raw_board)
            return httpx.Response(200, json=self.board)
        if request.url.path == "/api/playlist_songs/9001":
            if self.songs_fail:
                return httpx.Response(503)
            return httpx.Response(200, json=[{**m, "char": "Standard", "diff": "ExpertPlus" if i == 0 else "Expert"}
                                             for i, m in enumerate(self.board["maps"])])
        return httpx.Response(404)


@pytest.fixture
def console(tmp_path):
    public = PublicFixture()
    control = Control(tmp_path, transport=httpx.MockTransport(public))
    control.auth.set_admin(ADMIN_USER, ADMIN_PASSWORD)
    admin_app, proxy_app = make_apps(control)
    with TestClient(proxy_app) as proxy, TestClient(admin_app, headers=HEADERS) as admin:
        login_admin(admin)
        yield admin, proxy, None, control, public


@pytest.fixture
def public_console(tmp_path):
    public = PublicFixture()
    control = Control(tmp_path / "private-data", admin_port=29764, proxy_port=29080,
                      public_url="https://jbsl-qualifier.rynan.com/", transport=httpx.MockTransport(public))
    control.auth.set_admin(ADMIN_USER, ADMIN_PASSWORD)
    admin_app, proxy_app = make_apps(control)
    # The browser uses HTTPS, while cloudflared connects to the app over HTTP.
    origin = "https://jbsl-qualifier.rynan.com"
    async def tunnel_admin(scope, receive, send):
        if scope["type"] == "http":
            scope["scheme"] = "http"
        await admin_app(scope, receive, send)
    with TestClient(proxy_app, base_url=origin.replace("https:", "http:")) as proxy, TestClient(
            tunnel_admin, base_url=origin, headers={**HEADERS, "Origin": origin}) as admin:
        login_admin(admin)
        yield admin, proxy, None, control, public


def login_admin(client):
    response = client.post("/admin/api/login", json={"username": ADMIN_USER, "password": ADMIN_PASSWORD})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrfToken"]
    return response


def behavior(admin, **changes):
    data = admin.get("/admin/api/overview").json()
    data["behavior"].update(changes)
    response = admin.put("/admin/api/settings", json={"behavior": data["behavior"], "generation": data["generation"]})
    assert response.status_code == 200, response.text


def edit(admin, league=3023):
    data = admin.get(f"/admin/api/leagues/{league}").json()
    return {"fixture": data["entry"]["fixture"], "expectedRevision": data["expectedRevision"]}


def test_console_serves_login_help_and_offline_swagger(console):
    admin, proxy, score, *_ = console
    for path in ("/admin/", "/guide", "/static/app.js", "/static/help.js", "/static/style.css"):
        assert admin.get(path).status_code == 200
    for client in (admin, proxy):
        assert client.get("/healthz").status_code == 200
    for client in (proxy,):
        page = client.get("/docs")
        assert page.status_code == 200 and "cdn" not in page.text and "https://" not in page.text
        assert client.get("/docs-assets/vendor/swagger-ui/swagger-ui-bundle.js").status_code == 200
        spec = client.get("/openapi.json").json()
        assert spec["servers"] == [{"url": "/", "description": "この Swagger UI と同じ接続先"}]
        assert spec["components"]["schemas"]["Leaderboard"]["properties"]["qualifier"]["properties"]["revision"]["type"] == "string"


def test_admin_csrf_host_and_content_type(console):
    admin, proxy, *_ = console
    assert admin.post("/admin/api/logs/clear", json={}, headers={"X-JBSL-Admin": ""}).status_code == 403
    assert admin.post("/admin/api/logs/clear", json={}, headers={"Origin": "https://evil.invalid"}).status_code == 403
    assert admin.get("/admin/api/overview", headers={"Host": "evil.invalid"}).status_code == 403
    assert admin.post("/admin/api/logs/clear", content="{}").status_code == 415
    assert admin.post("/admin/api/logs/clear", json={}, headers={"Origin": "http://testserver"}).status_code == 200
    assert proxy.get("/api/active_league").status_code == 404
    assert proxy.get("/api/playlist_songs/9001").status_code == 404
    assert proxy.get("/admin/").status_code == 404


def test_public_overview_and_served_assets_do_not_reveal_internal_addresses(public_console):
    admin, proxy, _, control, _ = public_console
    origin = "https://jbsl-qualifier.rynan.com"
    overview = admin.get("/admin/api/overview")
    data = overview.json()
    assert data["publicMode"] is True
    assert data["urls"] == {"admin": origin, "proxy": origin}
    assert data["viewerConfig"] == {"leaderboardApiUrl": origin + "/leaderboard/api/", "allowDevelopmentHttp": False}
    assert "dataDirectory" not in data
    forbidden = ["127.0.0.1", "localhost", ":18080", ":18764", ":18081", ":18763", ":18082", ":18765",
                 ":29080", ":29764", str(control.data_dir), str(ROOT)]
    responses = [overview, admin.get("/admin/"), admin.get("/guide"), proxy.get("/docs"), proxy.get("/openapi.json")]
    for path in (ROOT / "static").rglob("*"):
        if path.is_file() and "vendor" not in path.parts:
            relative = path.relative_to(ROOT / "static").as_posix()
            responses.extend([admin.get("/static/" + relative), proxy.get("/docs-assets/" + relative)])
    for response in responses:
        assert response.status_code == 200, response.url
        assert all(secret not in response.text for secret in forbidden), response.url
    for path in ("/config.json", "/config.example.json", "/data/control.json", "/static/config.json", "/docs-assets/config.json"):
        assert admin.get(path).status_code == 404
        assert proxy.get(path).status_code == 404
    # A local visit while sharing must not return a second, internal version of the overview.
    local = admin.get("/admin/api/overview", headers={"Host": "localhost:29764", "Origin": "http://localhost:29764"})
    assert local.status_code == 200 and local.json()["urls"] == data["urls"]
    assert "dataDirectory" not in local.json()
    assert all(secret not in local.text for secret in forbidden)


@pytest.mark.parametrize("host", ["evil.invalid", "jbsl-qualifier.rynan.com.evil.invalid", "jbsl-qualifier.rynan.com:18080",
                                  "user@jbsl-qualifier.rynan.com", "jbsl-qualifier.rynan.com/path"])
def test_public_host_cannot_be_bypassed_with_forwarded_headers(public_console, host):
    admin, proxy, *_ = public_console
    headers = {"Host": host, "X-Forwarded-Host": "jbsl-qualifier.rynan.com", "Forwarded": "host=jbsl-qualifier.rynan.com;proto=https"}
    assert admin.get("/admin/api/overview", headers=headers).status_code == 403
    assert proxy.get("/leaderboard/api/3023", headers=headers).status_code == 403


def test_public_admin_preserves_origin_and_write_checks(public_console):
    admin, _, _, control, _ = public_console
    before = control.path.read_bytes()
    for origin in ("https://evil.invalid", "http://jbsl-qualifier.rynan.com", "http://localhost:29764", "null"):
        assert admin.post("/admin/api/logs/clear", json={}, headers={"Origin": origin}).status_code == 403
    assert admin.post("/admin/api/logs/clear", json={}, headers={"X-JBSL-Admin": ""}).status_code == 403
    assert admin.post("/admin/api/logs/clear", json={}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert admin.post("/admin/api/logs/clear", content="{}").status_code == 415
    assert control.path.read_bytes() == before
    assert admin.post("/admin/api/logs/clear", json={}).status_code == 200


@pytest.mark.parametrize("proto", ["http", "https"])
def test_public_redirects_use_configured_https_origin(public_console, proto):
    admin, proxy, *_ = public_console
    for client, path in ((admin, "/admin"), (admin, "/static"), (proxy, "/docs/"), (proxy, "/docs-assets")):
        response = client.get(path, headers={"X-Forwarded-Proto": proto, "X-Forwarded-Host": "private.invalid:9999"}, follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"].startswith("https://jbsl-qualifier.rynan.com/")
    response = admin.get("/", follow_redirects=False)
    assert response.headers["location"] == "/admin/"


def test_public_edit_preview_save_and_injected_traffic(public_console):
    admin, proxy, _, control, _ = public_console
    assert admin.post("/admin/api/leagues/refresh", json={}).status_code == 200
    body = edit(admin)
    body["fixture"]["auto_add_ranking_sids"] = False
    assert admin.post("/admin/api/leagues/3023/preview", json=body).status_code == 200
    assert admin.put("/admin/api/leagues/3023", json=body).status_code == 200
    behavior(admin, proxy_fault="upstream_invalid", proxy_delay_ms=30)
    response = proxy.get("/leaderboard/api/3023")
    assert response.status_code == 200 and response.text == "{invalid"
    rows = admin.get("/admin/api/logs").json()["items"]
    row = next(row for row in rows if row.get("source") == "injected")
    assert row["errorCode"] == "upstream_invalid" and row["elapsedMs"] >= 25
    assert row["requestId"] == response.headers["x-request-id"]
    behavior(admin, proxy_fault="none", proxy_delay_ms=0)
    assert proxy.get("/leaderboard/api/3023").status_code == 200
    assert admin.get("/admin/api/state").json()["requests"]["proxy"]["leaderboard"] == 1


def test_public_probe_still_calls_the_internal_listener(public_console, monkeypatch):
    admin, _, _, control, _ = public_console
    client_class = httpx.AsyncClient
    calls = []
    def internal(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"league_id": 3023})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_class(transport=httpx.MockTransport(internal), **kwargs))
    response = admin.get("/admin/api/probe/3023")
    assert response.json() == {"status": 200, "body": {"league_id": 3023}}
    assert calls == [control.urls["proxy"] + "/leaderboard/api/3023"]


def test_import_autofills_duration_and_enables_ranking_participants(console):
    admin, proxy, _, control, public = console
    assert admin.post("/admin/api/leagues/refresh", json={}).status_code == 200
    data = admin.post("/admin/api/leagues/7001/import", json={}).json()
    fixture = data["entry"]["fixture"]
    assert fixture["participants"] == []
    assert fixture["auto_add_ranking_sids"] is True
    assert data["rankingSids"] == ["76561198000000000"]
    assert [m["song_duration_seconds"] for m in fixture["maps"]] == [195, 195]
    assert len(public.beatsaver_requests) == 2
    assert fixture["maps"][0]["difficulty"] == "ExpertPlus"
    assert fixture["maps"][1]["difficulty"] == "Expert"
    assert proxy.get("/leaderboard/api/7001").json() == public.board
    body = {"fixture": fixture, "expectedRevision": None}
    response = admin.put("/admin/api/leagues/7001", json=body)
    assert response.status_code == 200, response.text
    merged = proxy.get("/leaderboard/api/7001").json()
    assert merged["qualifier"]["enabled"] is False
    assert merged["participants"] == [{"sid": "76561198000000000", "name": "Test Player"}]
    assert merged["maps"][0]["scores"] == public.board["maps"][0]["scores"]
    assert public.requests.count("/leaderboard/api/7001") == 3
    behavior(admin, upstream_mode="snapshot")
    public.fail = True
    assert proxy.get("/leaderboard/api/7001").status_code == 200
    loaded = Control(control.data_dir)
    assert loaded.snapshot()["leagues"]["7001"]["fixture"] == fixture
    assert loaded.snapshot()["behavior"]["upstream_mode"] == "snapshot"


def test_refresh_failure_keeps_last_success_and_labels_error(console):
    admin, _, _, control, public = console
    admin.post("/admin/api/leagues/refresh", json={})
    before = copy.deepcopy(control.snapshot()["active"])
    public.fail = True
    assert admin.post("/admin/api/leagues/refresh", json={}).status_code == 503
    after = admin.get("/admin/api/leagues").json()["active"]
    assert after["items"] == before["items"] and after["fetchedAt"] == before["fetchedAt"]
    assert after["error"]


def test_missing_playlist_information_requires_explicit_fields(console):
    admin, proxy, _, _, public = console
    admin.post("/admin/api/leagues/refresh", json={})
    public.songs_fail = True
    entry = admin.post("/admin/api/leagues/7001/import", json={}).json()["entry"]
    assert entry["fixture"]["maps"][0]["difficulty"] == ""
    response = admin.put("/admin/api/leagues/7001", json={"fixture": entry["fixture"], "expectedRevision": None})
    assert response.status_code == 422
    assert proxy.get("/leaderboard/api/7001").json() == public.board


def test_settings_save_revision_preview_and_conflict(console):
    admin, proxy, *_ = console
    body = edit(admin)
    body["fixture"]["maps"][0]["qualifier_attempt_limit"] = 9
    preview = admin.post("/admin/api/leagues/3023/preview", json=body)
    assert preview.json()["merged"]["maps"][0]["qualifier_attempt_limit"] == 9
    assert proxy.get("/leaderboard/api/3023").json()["maps"][0]["qualifier_attempt_limit"] == 3
    saved = admin.put("/admin/api/leagues/3023", json=body)
    assert saved.status_code == 200
    assert saved.json()["entry"]["fixture"]["qualifier"]["revision"] == "43"
    assert admin.put("/admin/api/leagues/3023", json=body).status_code == 409
    assert proxy.get("/leaderboard/api/3023").json()["maps"][0]["qualifier_attempt_limit"] == 9


@pytest.mark.parametrize("change", ["limit", "duplicate_sid", "numeric_sid", "equal_window", "maps_missing", "nonqualifier", "bad_hash", "auto_sids"])
def test_invalid_league_edit_does_not_change_disk(console, change):
    admin, _, _, control, _ = console
    before = control.path.read_bytes()
    body = edit(admin)
    fixture = body["fixture"]
    if change == "limit": fixture["maps"][0]["qualifier_attempt_limit"] = True
    if change == "duplicate_sid": fixture["participants"] *= 2
    if change == "numeric_sid": fixture["participants"][0]["sid"] = 123
    if change == "equal_window": fixture["qualifier"]["starts_at"] = fixture["qualifier"]["ends_at"]
    if change == "maps_missing": fixture["maps"].pop()
    if change == "nonqualifier": fixture["qualifier"]["enabled"] = False
    if change == "bad_hash": fixture["maps"][0]["index"] = 0
    if change == "auto_sids": fixture["auto_add_ranking_sids"] = "false"
    assert admin.put("/admin/api/leagues/3023", json=body).status_code == 422
    assert control.path.read_bytes() == before


@pytest.mark.parametrize("change", [{"proxy_delay_ms": -1}, {"clock_offset_seconds": 31536001}, {"stub_sid": " x "},
                                   {"cache_stale_seconds": 10}, {"result_grace_seconds": True}, {"upstream_mode": "https://evil.invalid"}])
def test_invalid_behavior_is_atomic(console, change):
    admin, _, _, control, _ = console
    original = control.path.read_bytes()
    data = admin.get("/admin/api/overview").json()
    data["behavior"].update(change)
    result = admin.put("/admin/api/settings", json={"behavior": data["behavior"], "generation": data["generation"]})
    assert result.status_code == 422
    assert control.path.read_bytes() == original


def test_concurrent_saves_allow_only_one_revision(console):
    admin, _, _, control, _ = console
    body = edit(admin)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: admin.put("/admin/api/leagues/3023", json=body), range(4)))
    assert sorted(r.status_code for r in responses) == [200, 409, 409, 409]
    assert control.snapshot()["leagues"]["3023"]["fixture"]["qualifier"]["revision"] == "43"


def test_fault_scope_delay_recovery_and_secret_free_logs(console):
    admin, proxy, score, control, _ = console
    behavior(admin, proxy_fault="upstream_invalid", proxy_delay_ms=30)
    start = time.monotonic()
    response = proxy.get("/leaderboard/api/3023?ticket=SECRET-TICKET", headers={"Cookie": "SECRET-COOKIE"})
    assert response.status_code == 200 and response.text == "{invalid"
    assert time.monotonic() - start >= .025
    behavior(admin, proxy_fault="none", proxy_delay_ms=0)
    assert proxy.get("/leaderboard/api/3023").status_code == 200
    logs = admin.get("/admin/api/logs").json()["items"]
    assert "SECRET" not in json.dumps(logs)
    assert any(row.get("errorCode") == "upstream_invalid" for row in logs)
    assert any(row.get("elapsedMs", 0) >= 25 for row in logs)
    assert admin.get("/healthz").status_code == 200




def test_traffic_capacity_and_monotonic_ids():
    log = TrafficLog(3)
    for i in range(5): log.add(role="score", status=200, path="/test")
    assert [r["id"] for r in log.read()] == [3, 4, 5]
    log.clear()
    log.add(role="score", status=503)
    assert log.read(errors=True)[0]["id"] == 6


def test_public_client_allowlist(console):
    *_, control, public = console
    with pytest.raises(ValueError):
        asyncio.run(control.public.get("https://evil.invalid/"))
    assert public.requests == []


def test_missing_nested_fields_are_validation_errors(console):
    admin, *_ = console
    assert admin.put("/admin/api/leagues/3023", json={"fixture": {}, "expectedRevision": "42"}).status_code == 422


def test_failed_disk_write_keeps_old_memory_and_file(console, monkeypatch):
    _, _, _, control, _ = console
    before = control.path.read_bytes()
    old = control.snapshot()
    def fail(_):
        raise OSError("simulated full disk")
    monkeypatch.setattr(control, "_write", fail)
    with pytest.raises(OSError):
        control.save_behavior(Behavior(proxy_fault="upstream_unavailable"), 1)
    assert control.snapshot() is old and control.path.read_bytes() == before


@pytest.mark.parametrize("mode", ["live", "snapshot"])
def test_unconfigured_league_is_raw_pass_through_even_without_import(console, mode):
    admin, proxy, _, control, public = console
    behavior(admin, upstream_mode=mode)
    public.raw_board = b'{\n "league_id": 7001, "unknown_field": 1.00, "maps": []\n}\n'
    before = control.path.read_bytes()
    response = proxy.get("/leaderboard/api/7001", headers={"Cookie": "local-only", "Authorization": "local-only"})
    assert response.status_code == 200 and response.content == public.raw_board
    assert public.beatsaver_requests == []
    assert control.path.read_bytes() == before
    assert control.log.read(role="proxy")[-1]["source"] == "live"
    public.fail = True
    assert proxy.get("/leaderboard/api/7001").status_code == 503


def test_ranking_sids_follow_current_response_and_checkbox_persists(console):
    admin, proxy, _, control, public = console
    admin.post("/admin/api/leagues/refresh", json={})
    data = admin.post("/admin/api/leagues/7001/import", json={}).json()
    fixture = data["entry"]["fixture"]
    fixture["participants"] = [{"sid": "manual"}]
    assert admin.put("/admin/api/leagues/7001", json={"fixture": fixture, "expectedRevision": None}).status_code == 200
    public.board["total_rank"].append({"sid": "new-ranking-sid"})
    public.board["maps"][1]["scores"] = [{"sid": "map-only-sid"}, {"sid": "manual"}]
    assert proxy.get("/leaderboard/api/7001").json()["participants"] == [
        {"sid": "manual", "name": "manual"}, {"sid": "76561198000000000", "name": "Test Player"},
        {"sid": "new-ranking-sid", "name": "new-ranking-sid"}, {"sid": "map-only-sid", "name": "map-only-sid"}]
    body = edit(admin, 7001)
    body["fixture"]["auto_add_ranking_sids"] = False
    assert admin.post("/admin/api/leagues/7001/preview", json=body).json()["merged"]["participants"] == [{"sid": "manual", "name": "manual"}]
    assert admin.put("/admin/api/leagues/7001", json=body).status_code == 200
    assert proxy.get("/leaderboard/api/7001").json()["participants"] == [{"sid": "manual", "name": "manual"}]
    assert Control(control.data_dir).snapshot()["leagues"]["7001"]["fixture"]["auto_add_ranking_sids"] is False
    body = edit(admin, 7001)
    body["fixture"]["auto_add_ranking_sids"] = True
    assert admin.put("/admin/api/leagues/7001", json=body).status_code == 200
    assert len(proxy.get("/leaderboard/api/7001").json()["participants"]) == 4


def test_participant_names_match_preview_save_live_and_snapshot(console):
    admin, proxy, _, control, public = console
    sid = "76561198245534518"
    public.scoresaber_profiles[sid] = {"id": sid, "name": "リュナン"}
    admin.post("/admin/api/leagues/refresh", json={})
    data = admin.post("/admin/api/leagues/7001/import", json={}).json()
    fixture = data["entry"]["fixture"]
    fixture["participants"] = [{"sid": sid}]
    body = {"fixture": fixture, "expectedRevision": None}
    expected = [{"sid": sid, "name": "リュナン"}, {"sid": "76561198000000000", "name": "Test Player"}]
    assert admin.post("/admin/api/leagues/7001/preview", json=body).json()["merged"]["participants"] == expected
    assert admin.put("/admin/api/leagues/7001", json=body).json()["merged"]["participants"] == expected
    assert proxy.get("/leaderboard/api/7001").json()["participants"] == expected
    behavior(admin, upstream_mode="snapshot")
    assert proxy.get("/leaderboard/api/7001").json()["participants"] == expected
    assert public.scoresaber_requests == ["/api/v2/players/" + sid]
    assert control.snapshot()["leagues"]["7001"]["fixture"]["participants"] == [{"sid": sid}]


def test_existing_live_settings_get_beatsaver_duration_on_edit_and_relay(console):
    admin, proxy, _, control, public = console
    entry = copy.deepcopy(control.snapshot()["leagues"]["3023"])
    entry.update(source="live", upstream=public.board)
    for map_settings in entry["fixture"]["maps"]:
        map_settings["song_duration_seconds"] = None
    control.commit(lambda state: state["leagues"].update({"7001": entry}))
    before = control.path.read_bytes()
    assert [m["song_duration_seconds"] for m in proxy.get("/leaderboard/api/7001").json()["maps"]] == [195, 195]
    body = edit(admin, 7001)
    assert [m["song_duration_seconds"] for m in body["fixture"]["maps"]] == [195, 195]
    assert len(public.beatsaver_requests) == 2  # The editor reuses successful hash lookups.
    assert control.path.read_bytes() == before
    assert admin.put("/admin/api/leagues/7001", json=body).status_code == 200
    assert Control(control.data_dir).snapshot()["leagues"]["7001"]["fixture"]["maps"][0]["song_duration_seconds"] == 195


@pytest.mark.parametrize("status,duration", [(404, 195), (429, 195), (503, 195), (200, None), (200, 0), (200, -1),
                                            (200, True), (200, "195"), (200, float("nan")), (200, float("inf"))])
def test_beatsaver_failure_keeps_existing_durations_and_import_succeeds(console, status, duration):
    admin, _, _, _, public = console
    public.beatsaver_status, public.beatsaver_duration = status, duration
    public.board["maps"][0]["song_duration_seconds"] = 123.5
    admin.post("/admin/api/leagues/refresh", json={})
    response = admin.post("/admin/api/leagues/7001/import", json={})
    assert response.status_code == 200
    entry = response.json()["entry"]
    assert [m["song_duration_seconds"] for m in entry["fixture"]["maps"]] == [123.5, None]
    assert any("曲時間を取得できません" in note for note in entry["notes"])


def test_beatsaver_shared_hash_is_fetched_once_for_multiple_difficulties(console):
    admin, _, _, _, public = console
    public.board["maps"][1]["hash"] = public.board["maps"][0]["hash"].lower()
    admin.post("/admin/api/leagues/refresh", json={})
    entry = admin.post("/admin/api/leagues/7001/import", json={}).json()["entry"]
    assert [m["song_duration_seconds"] for m in entry["fixture"]["maps"]] == [195, 195]
    assert len(public.beatsaver_requests) == 1


def test_snapshot_edit_does_not_contact_beatsaver(console):
    admin, _, _, control, public = console
    entry = copy.deepcopy(control.snapshot()["leagues"]["3023"])
    entry.update(source="live", upstream=public.board)
    control.commit(lambda state: state["leagues"].update({"7001": entry}))
    behavior(admin, upstream_mode="snapshot")
    assert edit(admin, 7001)["fixture"] == entry["fixture"]
    assert public.requests == public.beatsaver_requests == []

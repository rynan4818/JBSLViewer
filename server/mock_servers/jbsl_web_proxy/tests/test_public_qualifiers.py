import asyncio
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from mock_servers.jbsl_web_proxy import control as control_module
from mock_servers.jbsl_web_proxy.admin_server import make_apps
from mock_servers.jbsl_web_proxy.config import ROOT, utc_now
from mock_servers.jbsl_web_proxy.control import Control
from mock_servers.jbsl_web_proxy.public_qualifiers import PUBLIC_API, ParticipantRateLimit
from mock_servers.jbsl_web_proxy.schemas import utc_text
from .test_admin import ACTIVE, ADMIN_PASSWORD, ADMIN_USER, PublicFixture, login_admin

ADD = PUBLIC_API + "/7001/participants"
PUBLIC_HEADERS = {"X-JBSL-Public": "1", "Origin": "http://testserver"}


def seed_public_qualifier(control):
    def update(state):
        entry = copy.deepcopy(state["leagues"]["3023"])
        entry["source"] = "live"
        entry["upstream"].update(league_id=7001, league_title=ACTIVE[0]["name"])
        entry["fixture"]["participants"] = []
        state["leagues"]["7001"] = entry
        state["active"] = {"items": copy.deepcopy(ACTIVE), "fetchedAt": utc_text(utc_now()), "error": None}
    control.commit(update)


@pytest.fixture
def public_page(tmp_path):
    upstream = PublicFixture()
    control = Control(tmp_path, transport=httpx.MockTransport(upstream))
    control.auth.set_admin(ADMIN_USER, ADMIN_PASSWORD)
    seed_public_qualifier(control)
    admin, proxy = make_apps(control)
    with TestClient(admin, headers=PUBLIC_HEADERS) as client, TestClient(proxy) as viewer:
        yield client, viewer, control, upstream


def test_public_catalog_and_login_link_need_no_session(public_page):
    client, _, control, upstream = public_page
    response = client.get(PUBLIC_API)
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == [{"id": 7001, "name": ACTIVE[0]["name"], "startsAt": "2020-01-01T00:00:00Z", "endsAt": "2035-09-30T15:00:00Z"}]
    assert data["canAddSid"] and not data["stale"] and data["source"] == "live"
    assert set(data) == {"items", "fetchedAt", "serverTime", "source", "stale", "canAddSid"}
    assert not upstream.requests and not client.cookies
    assert client.get("/qualifiers/").status_code == 200
    assert 'href="/qualifiers/"' in client.get("/admin/").text
    for path in ("/admin/api/overview", "/admin/api/leagues", "/admin/api/logs", "/admin/api/state"):
        assert client.get(path).status_code == 401


@pytest.mark.parametrize("condition", ["no_active", "not_saved", "sample", "disabled", "local_closed", "local_not_live",
                                       "local_ended", "upstream_closed", "upstream_not_live", "upstream_ended"])
def test_only_open_live_configured_qualifiers_can_be_listed_or_added(public_page, condition):
    client, _, control, _ = public_page
    def update(state):
        entry = state["leagues"]["7001"]
        fixture, active = entry["fixture"], state["active"]["items"][0]
        if condition == "no_active": state["active"]["items"] = []
        if condition == "not_saved": del state["leagues"]["7001"]
        if condition == "sample": entry["source"] = "sample"
        if condition == "disabled": fixture["qualifier"]["enabled"] = False
        if condition == "local_closed": fixture["isOpen"] = False
        if condition == "local_not_live": fixture["isLive"] = False
        if condition == "local_ended": fixture["end"] = utc_text(utc_now())
        if condition == "upstream_closed": active["isOpen"] = False
        if condition == "upstream_not_live": active["isLive"] = False
        if condition == "upstream_ended": active["end"] = utc_text(utc_now())
    control.commit(update)
    before = control.path.read_bytes()
    assert client.get(PUBLIC_API).json()["items"] == []
    assert client.post(ADD, json={"sid": "not-added"}).status_code == 404
    assert control.path.read_bytes() == before


def test_registration_before_qualifier_start_is_allowed(public_page):
    client, _, control, _ = public_page
    control.commit(lambda state: state["leagues"]["7001"]["fixture"]["qualifier"].update(starts_at="2035-09-01T00:00:00Z"))
    assert len(client.get(PUBLIC_API).json()["items"]) == 1
    assert client.post(ADD, json={"sid": "early-registration"}).json()["added"]


def test_add_is_persistent_append_only_and_duplicate_is_a_no_op(public_page):
    client, viewer, control, _ = public_page
    original = copy.deepcopy(control.snapshot())
    response = client.post(ADD, json={"sid": "  000Mixed-Case-SID  "})
    assert response.json() == {"leagueId": 7001, "added": True, "revision": "43"}
    expected = copy.deepcopy(original)
    expected["leagues"]["7001"]["fixture"]["participants"] = [{"sid": "000Mixed-Case-SID"}]
    expected["leagues"]["7001"]["fixture"]["qualifier"]["revision"] = "43"
    assert control.snapshot() == expected
    assert {"sid": "000Mixed-Case-SID", "name": "000Mixed-Case-SID"} in viewer.get("/leaderboard/api/7001").json()["participants"]
    assert Control(control.data_dir).snapshot() == expected
    before = control.path.read_bytes()
    assert client.post(ADD, json={"sid": "000Mixed-Case-SID"}).json() == {"leagueId": 7001, "added": False, "revision": "43"}
    assert control.path.read_bytes() == before
    assert "000Mixed-Case-SID" not in json.dumps(control.log.read())


def test_auto_ranking_sid_can_be_saved_manually_without_duplicate_projection(public_page):
    client, viewer, control, _ = public_page
    sid = "76561198000000000"
    assert client.post(ADD, json={"sid": sid}).json()["added"]
    assert control.snapshot()["leagues"]["7001"]["fixture"]["participants"] == [{"sid": sid}]
    assert viewer.get("/leaderboard/api/7001").json()["participants"].count({"sid": sid, "name": "Test Player"}) == 1


@pytest.mark.parametrize("body", [{}, {"sid": "new", "participants": []}, {"sid": "new", "delete": True},
    {"sid": ""}, {"sid": " "}, {"sid": None}, {"sid": 123}, {"sid": ["new"]}, {"sid": "a b"},
    {"sid": "a\nb"}, {"sid": "bad\x00sid"}, {"sid": "a\u200bb"}, {"sid": "x" * 129}])
def test_invalid_public_add_never_modifies_state(public_page, body):
    client, _, control, upstream = public_page
    original, before = control.snapshot(), control.path.read_bytes()
    assert client.post(ADD, json=body).status_code in {400, 422}
    assert control.snapshot() is original and control.path.read_bytes() == before
    assert upstream.requests == []


def test_public_registration_checks_origin_headers_body_and_methods(public_page):
    client, _, control, _ = public_page
    before = control.path.read_bytes()
    for headers in ({"Origin": ""}, {"Origin": "null"}, {"Origin": "https://evil.invalid"},
                    {"Host": "evil.invalid"}, {"Sec-Fetch-Site": "cross-site"}, {"X-JBSL-Public": "", "X-JBSL-Admin": "1"}):
        assert client.post(ADD, json={"sid": "new"}, headers=headers).status_code == 403
    assert client.post(ADD, content='{"sid":"new"}').status_code == 415
    assert client.post(ADD, json={"sid": "x" * 1500}).status_code == 413
    for method in ("PUT", "PATCH", "DELETE"):
        assert client.request(method, ADD, json={"sid": "new"}).status_code == 405
    assert client.put("/admin/api/leagues/7001", json={"participants": []}).status_code == 401
    assert control.path.read_bytes() == before


def test_sid_add_limit_cannot_be_bypassed_using_forwarded_headers(public_page):
    client, _, control, _ = public_page
    for index in range(10):
        response = client.post(ADD, json={"sid": f"sid-{index}"}, headers={"X-Forwarded-For": f"192.0.2.{index}", "CF-Connecting-IP": f"192.0.2.{index}"})
        assert response.status_code == 200
    before = control.path.read_bytes()
    response = client.post(ADD, json={"sid": "eleventh"})
    assert response.status_code == 429 and response.headers["retry-after"] == "60"
    assert control.path.read_bytes() == before


def test_rate_limit_window_and_independent_clients():
    limiter = ParticipantRateLimit()
    limiter.clock = lambda: 100.0
    for _ in range(10): limiter.check("client")
    limiter.check("another-client")
    limiter.clock = lambda: 160.0
    limiter.check("client")
    assert len(limiter.requests["client"]) == 1


def test_stale_catalog_refresh_failure_backoff_and_recovery(public_page, monkeypatch):
    client, _, control, upstream = public_page
    initial_now = utc_now()
    control.commit(lambda state: state["active"].update(fetchedAt=utc_text(initial_now-timedelta(seconds=61))))
    upstream.fail = True
    catalog = client.get(PUBLIC_API).json()
    assert catalog["stale"] and not catalog["canAddSid"] and catalog["items"]
    assert client.post(ADD, json={"sid": "no-save"}).status_code == 503
    assert client.get(PUBLIC_API).json()["stale"]
    assert len(upstream.requests) == 1
    assert control.snapshot()["leagues"]["7001"]["fixture"]["participants"] == []
    upstream.fail = False
    monkeypatch.setattr(control_module, "utc_now", lambda: initial_now+timedelta(seconds=62))
    catalog = client.get(PUBLIC_API).json()
    assert not catalog["stale"] and catalog["canAddSid"]
    assert len(upstream.requests) == 2
    assert client.post(ADD, json={"sid": "recovered"}).status_code == 200
    assert len(upstream.requests) == 2


def test_expired_successful_cache_and_concurrent_readers_share_one_fetch(public_page):
    _, _, control, upstream = public_page
    control.commit(lambda state: state["active"].update(fetchedAt=utc_text(utc_now()-timedelta(seconds=61))))
    async def delayed(request):
        await asyncio.sleep(.03)
        return upstream(request)
    control.public.transport = httpx.MockTransport(delayed)
    async def read_together():
        await asyncio.gather(*(control.refresh_public_active() for _ in range(8)))
    asyncio.run(read_together())
    assert upstream.requests == ["/api/active_league"]
    assert control.public_qualifiers()["canAddSid"]


def test_snapshot_uses_saved_catalog_without_contacting_upstream(public_page):
    client, _, control, upstream = public_page
    def update(state):
        state["behavior"]["upstream_mode"] = "snapshot"
        state["active"].update(fetchedAt="2020-01-01T00:00:00Z", error="old upstream error")
    control.commit(update)
    upstream.fail = True
    data = client.get(PUBLIC_API).json()
    assert data["source"] == "snapshot" and not data["stale"] and data["canAddSid"]
    assert client.post(ADD, json={"sid": "offline-sid"}).status_code == 200
    assert not upstream.requests


def test_no_previous_catalog_is_unavailable_instead_of_current_empty(public_page):
    client, _, control, upstream = public_page
    control.commit(lambda state: state.update(active={"items": [], "fetchedAt": None, "error": None}))
    upstream.invalid = True
    data = client.get(PUBLIC_API).json()
    assert data["items"] == [] and data["stale"] and not data["canAddSid"]


def test_concurrent_additions_keep_every_sid_and_same_sid_is_idempotent(public_page):
    _, _, control, _ = public_page
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda sid: control.add_public_participant(7001, sid), ["shared"] * 4 + [f"different-{i}" for i in range(4)]))
    assert sum(result["added"] for result in results) == 5
    fixture = control.snapshot()["leagues"]["7001"]["fixture"]
    assert {p["sid"] for p in fixture["participants"]} == {"shared", "different-0", "different-1", "different-2", "different-3"}
    assert fixture["qualifier"]["revision"] == "47"


def test_admin_stale_edit_conflicts_then_authenticated_removal_succeeds(public_page):
    client, viewer, control, _ = public_page
    old = copy.deepcopy(control.snapshot()["leagues"]["7001"]["fixture"])
    assert client.post(ADD, json={"sid": "public-sid"}).status_code == 200
    client.headers["X-JBSL-Admin"] = "1"
    login_admin(client)
    assert client.put("/admin/api/leagues/7001", json={"fixture": old, "expectedRevision": "42"}).status_code == 409
    latest = client.get("/admin/api/leagues/7001").json()
    fixture = latest["entry"]["fixture"]
    assert {"sid": "public-sid"} in fixture["participants"]
    fixture["participants"].remove({"sid": "public-sid"})
    assert client.put("/admin/api/leagues/7001", json={"fixture": fixture, "expectedRevision": latest["expectedRevision"]}).status_code == 200
    assert "public-sid" not in {p["sid"] for p in viewer.get("/leaderboard/api/7001").json()["participants"]}


def test_add_rechecks_closure_after_catalog_was_loaded(public_page):
    client, _, control, _ = public_page
    assert client.get(PUBLIC_API).json()["items"]
    control.commit(lambda state: state["leagues"]["7001"]["fixture"].update(isOpen=False))
    before = control.path.read_bytes()
    assert client.post(ADD, json={"sid": "too-late"}).status_code == 404
    assert control.path.read_bytes() == before


def test_save_failure_keeps_file_and_memory_and_does_not_leak_details(public_page, monkeypatch):
    client, _, control, _ = public_page
    before, original = control.path.read_bytes(), control.snapshot()
    def fail(_):
        raise OSError("private-disk-location 127.0.0.1:9999")
    monkeypatch.setattr(control, "_write", fail)
    response = client.post(ADD, json={"sid": "not-saved"})
    assert response.status_code == 503
    assert "private-disk-location" not in response.text and "127.0.0.1" not in response.text
    assert control.path.read_bytes() == before and control.snapshot() is original


def test_public_host_https_tunnel_add_and_privacy(tmp_path):
    origin = "https://jbsl-qualifier.rynan.com"
    control = Control(tmp_path, public_url=origin, transport=httpx.MockTransport(PublicFixture()))
    seed_public_qualifier(control)
    admin, _ = make_apps(control)
    async def tunnel(scope, receive, send):
        if scope["type"] == "http": scope["scheme"] = "http"
        await admin(scope, receive, send)
    with TestClient(tunnel, base_url=origin, headers={"X-JBSL-Public": "1", "Origin": origin}) as client:
        assert client.post(ADD, json={"sid": "public-origin-sid"}).status_code == 200
        assert client.get("/qualifiers", follow_redirects=False).headers["location"] == origin + "/qualifiers/"
        for path in (PUBLIC_API, "/qualifiers/", "/static/qualifiers.js", "/static/qualifiers.css"):
            response = client.get(path)
            assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
            for forbidden in ("127.0.0.1", "localhost", ":18080", ":18764", str(ROOT), str(control.data_dir), "csrfToken", "password_hash"):
                assert forbidden not in response.text
        assert not client.cookies

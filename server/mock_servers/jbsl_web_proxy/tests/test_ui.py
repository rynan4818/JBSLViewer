"""Browser checks using the optional requirements-dev.txt dependencies."""
import contextlib
import asyncio
import json
import os
import re
import socket
import threading
import time
from urllib.parse import urlsplit

import httpx
import pytest
import uvicorn

from mock_servers.jbsl_web_proxy.__main__ import ManagedServer
from mock_servers.jbsl_web_proxy.admin_server import make_apps
from mock_servers.jbsl_web_proxy.control import Control
from .test_admin import ADMIN_PASSWORD, ADMIN_USER, HEADERS, PublicFixture, login_admin
from .test_public_qualifiers import seed_public_qualifier

playwright_api = pytest.importorskip("playwright.sync_api")
expect = playwright_api.expect


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge" if os.name == "nt" else "chromium", headless=True)
        yield browser
        browser.close()


@pytest.fixture
def live_console(tmp_path, request):
    public = PublicFixture()
    with contextlib.ExitStack() as stack:
        sockets = [stack.enter_context(socket.socket()) for _ in range(2)]
        for listener in sockets:
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
        control = Control(tmp_path, admin_port=sockets[0].getsockname()[1], proxy_port=sockets[1].getsockname()[1],
                          transport=httpx.MockTransport(public), public_url=getattr(request, "param", ""))
        control.auth.set_admin(ADMIN_USER, ADMIN_PASSWORD)
        servers = [ManagedServer(uvicorn.Config(app, log_level="error")) for app in make_apps(control)]
        threads = [threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
                   for server, listener in zip(servers, sockets)]
        for thread in threads:
            thread.start()
        try:
            deadline = time.monotonic() + 10
            while not all(server.started for server in servers):
                assert time.monotonic() < deadline, "Test server startup timed out"
                time.sleep(.01)
            with httpx.Client(base_url=control.urls["admin"], headers=HEADERS, trust_env=False) as client:
                login_admin(client)
                assert client.post("/admin/api/leagues/refresh", json={}).status_code == 200
            yield control, public
        finally:
            for server in servers:
                server.should_exit = True
            for thread in threads:
                thread.join(timeout=5)


def browser_login(page):
    expect(page.locator("#login-view")).to_be_visible()
    expect(page.locator("#app-view")).not_to_be_visible()
    page.get_by_label("ユーザー名", exact=True).fill(ADMIN_USER)
    page.get_by_label("パスワード", exact=True).fill(ADMIN_PASSWORD)
    page.get_by_role("button", name="ログイン", exact=True).click()
    expect(page.locator("#app-view")).to_be_visible()
    expect(page.locator("#operator")).to_have_text(ADMIN_USER)
    expect(page.locator("#saved-leagues [data-league='3023']")).to_be_visible()


def route_public_tunnel(context, control, client):
    origin = control.base_settings.public_url
    if not origin:
        return
    def tunnel(route):
        request = route.request
        url = urlsplit(request.url)
        if url.scheme + "://" + url.netloc != origin:
            route.abort()
            return
        role = "proxy" if (url.path.startswith(("/leaderboard/api/", "/docs-assets/"))
                           or url.path in {"/docs", "/docs/", "/docs-assets", "/openapi.json", "/__mock__/state"}) else "admin"
        response = client.request(request.method, control.urls[role] + url.path + ("?" + url.query if url.query else ""),
                                  headers={**request.all_headers(), "host": url.netloc, "x-forwarded-proto": "https"},
                                  content=request.post_data_buffer)
        headers = {key: value for key, value in response.headers.items() if key not in {"content-length", "transfer-encoding", "content-encoding"}}
        route.fulfill(status=response.status_code, headers=headers, body=response.content)
    context.route("**/*", tunnel)


@pytest.mark.parametrize("zone,local_end,local_start,edited_end,expected_utc", [
    ("Asia/Tokyo", "2035-10-01T00:00:00.125", "2035-09-01T10:02:03.456", "2035-10-02T12:34:56", "2035-10-02T03:34:56.000Z"),
    ("America/New_York", "2035-09-30T11:00:00.125", "2035-08-31T21:02:03.456", "2035-10-02T12:34:56", "2035-10-02T16:34:56.000Z"),
    ("Asia/Kathmandu", "2035-09-30T20:45:00.125", "2035-09-01T06:47:03.456", "2035-10-02T12:34:56", "2035-10-02T06:49:56.000Z"),
])
def test_local_datetime_display_roundtrip_and_edited_save(browser, live_console, zone, local_end, local_start, edited_end, expected_utc):
    control, _ = live_console
    def setup(state):
        fixture = state["leagues"]["3023"]["fixture"]
        fixture["end"] = "2035-09-30T15:00:00.125Z"
        fixture["qualifier"].update(starts_at="2035-09-01T01:02:03.456Z", ends_at=None)
    control.commit(setup)
    with browser.new_context(timezone_id=zone, locale="ja-JP") as context:
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(control.urls["admin"] + "/admin/")
        browser_login(page)
        page.locator('[data-league="3023"]').click()
        expect(page.locator("#q-end")).to_have_value(local_end)
        expect(page.locator("#q-start")).to_have_value(local_start)
        expect(page.locator("#q-until")).to_have_value("")
        expect(page.locator("#editor-timezone")).to_contain_text("ブラウザのローカル時刻")
        page.get_by_role("button", name="リーグ設定を保存", exact=True).click()
        expect(page.locator("#editor")).not_to_be_visible()
        saved = control.snapshot()["leagues"]["3023"]["fixture"]
        assert saved["end"] == "2035-09-30T15:00:00.125Z"
        assert saved["qualifier"]["starts_at"] == "2035-09-01T01:02:03.456Z"
        assert saved["qualifier"]["ends_at"] is None
        page.locator('[data-league="3023"]').click()
        page.locator("#q-end").fill(edited_end)
        page.get_by_role("button", name="JSON をプレビュー", exact=True).click()
        expect(page.locator("#preview-json")).to_contain_text(expected_utc)
        page.get_by_role("button", name="リーグ設定を保存", exact=True).click()
        expect(page.locator("#editor")).not_to_be_visible()
        assert control.snapshot()["leagues"]["3023"]["fixture"]["end"] == expected_utc
        assert errors == []


@pytest.mark.parametrize("live_console", ["https://jbsl-qualifier.rynan.com"], indirect=True)
def test_public_browser_settings_guide_probe_and_swagger(browser, live_console, tmp_path):
    control, _ = live_console
    origin = control.base_settings.public_url
    errors, requests = [], []
    with browser.new_context(locale="ja-JP", timezone_id="Asia/Tokyo", viewport={"width": 1440, "height": 1000}) as context, httpx.Client(trust_env=False) as client:
        # Emulate Tunnel's path routing while the browser stays on the public HTTPS origin.
        # All responses come from the real local listeners; no public DNS or service is used.
        def tunnel(route):
            request = route.request
            url = urlsplit(request.url)
            requests.append(request.url)
            if url.scheme + "://" + url.netloc != origin:
                route.abort()
                return
            path = url.path
            role = "proxy" if (path.startswith(("/leaderboard/api/", "/docs-assets/"))
                               or path in {"/docs", "/docs/", "/docs-assets", "/openapi.json", "/__mock__/state"}) else "admin"
            response = client.request(request.method, control.urls[role] + path + ("?" + url.query if url.query else ""),
                                      headers={**request.all_headers(), "host": url.netloc, "x-forwarded-proto": "https"},
                                      content=request.post_data_buffer)
            headers = {key: value for key, value in response.headers.items() if key not in {"content-length", "transfer-encoding", "content-encoding"}}
            route.fulfill(status=response.status_code, headers=headers, body=response.content)

        context.route("**/*", tunnel)
        context.on("page", lambda page: page.on("pageerror", lambda error: errors.append(str(error))))
        page = context.new_page()
        page.goto(origin + "/admin/")
        expect(page).to_have_url(origin + "/admin/")
        expect(page.locator("#login-view")).to_be_visible()
        page.screenshot(path=str(tmp_path / "public-login.png"), full_page=True)
        browser_login(page)
        cookie = next(cookie for cookie in context.cookies() if cookie["name"] == "jbsl_relay_admin")
        assert cookie["secure"] and cookie["httpOnly"] and cookie["sameSite"] == "Strict" and cookie["path"] == "/admin"
        expect(page.locator("#connection")).to_contain_text("jbsl-qualifier.rynan.com")
        expect(page.locator("#proxy-docs")).to_have_attribute("href", origin + "/docs")
        page.locator('[data-page="state"]').click()
        expect(page.locator("#viewer-config")).to_contain_text(origin + "/leaderboard/api/")
        expect(page.locator("#data-path")).not_to_be_visible()
        page.locator("#runtime-details-label").click()
        expect(page.locator("#request-counts")).to_contain_text('"leaderboard"')
        page.screenshot(path=str(tmp_path / "public-state.png"), full_page=True)
        for secret in ("127.0.0.1", ":18080", ":18764", str(control.data_dir), *control.urls.values()):
            assert secret not in page.content()

        page.locator('[data-page="settings"]').click()
        page.locator("#b-proxy_delay_ms").fill("5")
        page.get_by_role("button", name="サーバ設定を保存", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("サーバ設定を保存しました")
        assert control.snapshot()["behavior"]["proxy_delay_ms"] == 5
        page.locator('[data-page="leagues"]').click()
        page.locator('[data-league="3023"]').click()
        page.locator("#q-auto-sids").uncheck()
        page.get_by_role("button", name="JSON をプレビュー", exact=True).click()
        expect(page.locator("#preview-json")).to_contain_text('"league_id": 3023')
        page.locator("#probe-league").click()
        expect(page.locator("#preview-json")).to_contain_text("HTTP 200")
        page.get_by_role("button", name="リーグ設定を保存", exact=True).click()
        expect(page.locator("#editor")).not_to_be_visible()
        assert control.snapshot()["leagues"]["3023"]["fixture"]["auto_add_ranking_sids"] is False

        guide = context.new_page()
        guide.goto(origin + "/guide")
        expect(guide.locator("#architecture")).to_contain_text("実行状態 → 接続先")
        assert "127.0.0.1" not in guide.content() and ":18080" not in guide.content()
        guide.screenshot(path=str(tmp_path / "public-guide.png"))

        docs = context.new_page()
        docs.goto(origin + "/docs")
        operation = docs.locator(".opblock").filter(has_text="リーグ情報を中継").first
        operation.locator(".opblock-summary").click()
        operation.get_by_role("button", name="Try it out", exact=True).click()
        with docs.expect_response(origin + "/leaderboard/api/3023") as executed:
            operation.get_by_role("button", name="Execute", exact=True).click()
        assert executed.value.status == 200
        expect(operation.locator(".live-responses-table")).to_contain_text('"league_id": 3023')
        docs.screenshot(path=str(tmp_path / "public-swagger.png"), full_page=True)
        assert all(url.startswith(origin + "/") for url in requests)
        assert any(row["role"] == "proxy" for row in control.log.read())
        page.locator("#logout").click()
        expect(page.locator("#login-view")).to_be_visible()
        expect(page.locator("#app-view")).not_to_be_visible()
        page.reload()
        expect(page.locator("#login-view")).to_be_visible()
        assert not any(cookie["name"] == "jbsl_relay_admin" for cookie in context.cookies())
        assert errors == []


def test_unchanged_repeated_dst_time_keeps_original_instant(browser, live_console):
    control, _ = live_console
    control.commit(lambda state: state["leagues"]["3023"]["fixture"].update(end="2035-11-04T06:30:00.000Z"))
    with browser.new_context(timezone_id="America/New_York") as context:
        page = context.new_page()
        page.goto(control.urls["admin"] + "/admin/")
        browser_login(page)
        page.locator('[data-league="3023"]').click()
        expect(page.locator("#q-end")).to_have_value("2035-11-04T01:30")
        page.get_by_role("button", name="リーグ設定を保存", exact=True).click()
        expect(page.locator("#editor")).not_to_be_visible()
        assert control.snapshot()["leagues"]["3023"]["fixture"]["end"] == "2035-11-04T06:30:00.000Z"


def test_imported_duration_and_participant_checkbox_preview_save_reload(browser, live_console, tmp_path):
    control, public = live_console
    with browser.new_context(timezone_id="Asia/Tokyo", locale="ja-JP", viewport={"width": 1440, "height": 1000}) as context:
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(control.urls["admin"] + "/admin/")
        browser_login(page)
        page.locator('[data-league="7001"]').click()
        expect(page.locator("#q-auto-sids")).to_be_checked()
        expect(page.locator("#map-duration-0")).to_have_value("195")
        expect(page.locator("#map-duration-1")).to_have_value("195")
        expect(page.locator("#ranking-sids")).to_contain_text("76561198000000000")
        page.locator("#q-participants").fill("manual-sid")
        page.get_by_role("button", name="JSON をプレビュー", exact=True).click()
        expect(page.locator("#preview-json")).to_contain_text('"participants"')
        assert json.loads(page.locator("#preview-json").inner_text())["participants"] == [
            {"sid": "manual-sid", "name": "manual-sid"}, {"sid": "76561198000000000", "name": "Test Player"}]
        page.screenshot(path=str(tmp_path / "league-editor.png"), full_page=True)
        page.locator("#q-auto-sids").uncheck()
        page.get_by_role("button", name="JSON をプレビュー", exact=True).click()
        expect(page.locator("#preview-json")).to_contain_text(re.compile(r'"participants":\s*\[\s*\{\s*"sid":\s*"manual-sid",\s*"name":\s*"manual-sid"\s*}\s*]'))
        assert json.loads(page.locator("#preview-json").inner_text())["participants"] == [{"sid": "manual-sid", "name": "manual-sid"}]
        expect(page.locator("#ranking-sids")).to_contain_text("自動追加はOFF")
        page.get_by_role("button", name="リーグ設定を保存", exact=True).click()
        expect(page.locator("#editor")).not_to_be_visible()
        assert control.snapshot()["leagues"]["7001"]["fixture"]["auto_add_ranking_sids"] is False
        page.reload()
        page.locator('#saved-leagues [data-league="7001"]').click()
        expect(page.locator("#q-auto-sids")).not_to_be_checked()
        page.get_by_role("button", name="JSON をプレビュー", exact=True).click()
        expect(page.locator("#preview-json")).to_contain_text('"participants"')
        assert json.loads(page.locator("#preview-json").inner_text())["participants"] == [{"sid": "manual-sid", "name": "manual-sid"}]
        assert len(public.beatsaver_requests) == 2
        assert errors == []


def test_login_error_reload_expiry_and_mobile_layout(browser, live_console, tmp_path):
    control, _ = live_console
    with browser.new_context(locale="ja-JP", viewport={"width": 390, "height": 844}) as context:
        page = context.new_page()
        errors, requested = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requested.append(urlsplit(request.url).path))
        page.goto(control.urls["admin"] + "/admin/")
        expect(page.locator("#login-view")).to_be_visible()
        assert [path for path in requested if path.startswith("/admin/api/")] == ["/admin/api/me"]
        card = page.locator(".login-card").bounding_box()
        assert card["x"] >= 0 and card["x"] + card["width"] <= 390
        page.screenshot(path=str(tmp_path / "mobile-login.png"), full_page=True)
        page.get_by_label("ユーザー名", exact=True).fill(ADMIN_USER)
        page.get_by_label("パスワード", exact=True).fill("wrong-password")
        page.get_by_role("button", name="ログイン", exact=True).click()
        expect(page.locator("#login-error")).to_have_text("ユーザー名またはパスワードが違います。")
        expect(page.locator("#password")).to_have_value("")
        expect(page.locator("#app-view")).not_to_be_visible()
        browser_login(page)
        cookie = next(cookie for cookie in context.cookies() if cookie["name"] == "jbsl_relay_admin")
        assert not cookie["secure"] and cookie["httpOnly"]
        page.reload()
        expect(page.locator("#app-view")).to_be_visible()
        page.locator('[data-league="3023"]').click()
        expect(page.locator("#editor")).to_be_visible()
        control.auth.clock = lambda: time.time() + 28801
        page.get_by_role("button", name="JSON をプレビュー", exact=True).click()
        expect(page.locator("#login-view")).to_be_visible()
        expect(page.locator("#login-error")).to_contain_text("有効期限が切れました")
        expect(page.locator("#editor")).not_to_be_visible()
        for selector in ("#saved-leagues", "#map-fields", "#preview-json", "#viewer-config", "#effective-end"):
            expect(page.locator(selector)).to_have_text("")
        control.auth.clock = time.time
        browser_login(page)
        page.locator('[data-page="traffic"]').click()
        expect(page.locator("#log-count")).to_contain_text("件表示")
        page.locator("#logout").click()
        expect(page.locator("#login-view")).to_be_visible()
        count = sum(path == "/admin/api/logs" for path in requested)
        page.wait_for_timeout(3300)  # One complete automatic log refresh interval after logout.
        assert sum(path == "/admin/api/logs" for path in requested) == count
        assert errors == []


def test_pending_editor_response_cannot_reopen_after_logout(browser, live_console, monkeypatch):
    control, _ = live_console
    started, release, completed = threading.Event(), threading.Event(), threading.Event()
    original = control.league_for_edit
    async def delayed(league_id):
        entry = await original(league_id)
        started.set()
        while not release.is_set():
            await asyncio.sleep(.01)
        completed.set()
        return entry
    monkeypatch.setattr(control, "league_for_edit", delayed)
    with browser.new_context() as context:
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(control.urls["admin"] + "/admin/")
        browser_login(page)
        try:
            page.locator('[data-league="3023"]').click()
            assert started.wait(5)
            page.locator("#logout").click()
            expect(page.locator("#login-view")).to_be_visible()
            release.set()
            assert completed.wait(5)
            page.wait_for_timeout(200)
            expect(page.locator("#editor")).not_to_be_visible()
            expect(page.locator("#app-view")).not_to_be_visible()
            expect(page.locator("#saved-leagues")).to_have_text("")
            assert errors == []
        finally:
            release.set()


@pytest.mark.parametrize("live_console", ["", "https://jbsl-qualifier.rynan.com"], indirect=True, ids=["local", "public"])
@pytest.mark.parametrize("width", [1440, 390], ids=["desktop", "mobile"])
def test_public_qualifier_link_add_duplicate_and_layout(browser, live_console, tmp_path, width):
    control, _ = live_console
    seed_public_qualifier(control)
    control.commit(lambda state: state["active"]["items"][0].update(name="JBSL Qualifier 検証リーグ"))
    origin = control.base_settings.public_url or control.urls["admin"]
    with browser.new_context(locale="ja-JP", timezone_id="Asia/Tokyo", viewport={"width": width, "height": 1000 if width > 760 else 844}) as context, httpx.Client(trust_env=False) as client:
        route_public_tunnel(context, control, client)
        page = context.new_page()
        errors, requests = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requests.append(request))
        page.goto(origin + "/admin/")
        expect(page.locator("#public-qualifiers")).to_be_visible()
        page.screenshot(path=str(tmp_path / "login-public-link.png"), full_page=True)
        page.locator("#public-qualifiers").click()
        expect(page).to_have_url(origin + "/qualifiers/")
        expect(page.locator("#league-count")).to_have_text("1リーグ")
        card = page.locator('[data-league="7001"]')
        expect(card).to_be_visible()
        expect(page.locator('[data-league="3023"]')).to_have_count(0)
        bounds = card.bounding_box()
        assert 0 <= bounds["x"] and bounds["x"] + bounds["width"] <= width
        page.screenshot(path=str(tmp_path / "qualifiers.png"), full_page=True)
        # A delayed refresh must preserve the typed SID and prevent a concurrent submission.
        card.get_by_label("追加するSID", exact=True).fill("kept-after-refresh")
        held = []
        def hold_catalog(route):
            held.append(route)
        page.route(origin + "/public/api/qualifier-leagues", hold_catalog)
        page.get_by_role("button", name="一覧を更新", exact=True).click()
        expect(page.locator("#league-list")).to_have_attribute("aria-busy", "true")
        expect(card.get_by_label("追加するSID", exact=True)).to_be_disabled()
        expect(card.get_by_role("button", name="SIDを追加", exact=True)).to_be_disabled()
        card.locator("form").dispatch_event("submit")
        assert not any(request.method == "POST" for request in requests)
        assert len(held) == 1
        response = client.get(control.urls["admin"] + "/public/api/qualifier-leagues",
                              headers={"Host": urlsplit(origin).netloc, "Origin": origin})
        held[0].fulfill(status=response.status_code, content_type="application/json", body=response.content)
        page.unroute(origin + "/public/api/qualifier-leagues", hold_catalog)
        expect(card.get_by_label("追加するSID", exact=True)).to_be_enabled()
        expect(card.get_by_label("追加するSID", exact=True)).to_have_value("kept-after-refresh")
        card.get_by_label("追加するSID", exact=True).fill("bad sid")
        card.get_by_role("button", name="SIDを追加", exact=True).click()
        expect(card.locator(".sid-result")).to_contain_text("空白・改行を含まない")
        assert control.snapshot()["leagues"]["7001"]["fixture"]["participants"] == []
        card.get_by_label("追加するSID", exact=True).fill("  000Web-Qualifier-SID  ")
        card.get_by_role("button", name="SIDを追加", exact=True).click()
        expect(card.locator(".sid-result")).to_have_text("SIDを追加しました。")
        fixture = control.snapshot()["leagues"]["7001"]["fixture"]
        assert fixture["participants"] == [{"sid": "000Web-Qualifier-SID"}]
        assert fixture["qualifier"]["revision"] == "43"
        card.get_by_label("追加するSID", exact=True).fill("000Web-Qualifier-SID")
        card.get_by_role("button", name="SIDを追加", exact=True).click()
        expect(card.locator(".sid-result")).to_have_text("このSIDは登録済みです。")
        assert control.snapshot()["leagues"]["7001"]["fixture"] == fixture
        page.reload()
        expect(page.locator('[data-league="7001"]')).to_be_visible()
        assert json.loads(control.path.read_text(encoding="utf-8"))["leagues"]["7001"]["fixture"]["participants"] == [{"sid": "000Web-Qualifier-SID"}]
        assert not context.cookies()
        paths = [urlsplit(request.url).path for request in requests]
        assert [path for path in paths if path.startswith("/admin/api/")] == ["/admin/api/me"]
        assert paths.count("/public/api/qualifier-leagues/7001/participants") == 2
        for request in requests:
            if request.method == "POST":
                assert "cookie" not in request.all_headers() and "x-csrf-token" not in request.all_headers()
        page.get_by_role("link", name="管理者ログインへ", exact=True).click()
        expect(page.locator("#login-view")).to_be_visible()
        assert errors == []


def test_public_qualifier_closure_stale_catalog_recovery_and_safe_text(browser, live_console):
    from datetime import timedelta
    from mock_servers.jbsl_web_proxy.config import utc_now
    from mock_servers.jbsl_web_proxy.schemas import utc_text
    control, upstream = live_console
    seed_public_qualifier(control)
    origin = control.urls["admin"]
    with browser.new_context(locale="ja-JP") as context:
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(origin + "/qualifiers/")
        card = page.locator('[data-league="7001"]')
        expect(card.locator("h2")).to_have_text("実API形式テスト <script>")
        assert card.locator("h2 script").count() == 0
        control.commit(lambda state: state["leagues"]["7001"]["fixture"].update(isOpen=False))
        card.get_by_label("追加するSID", exact=True).fill("late-sid")
        card.get_by_role("button", name="SIDを追加", exact=True).click()
        expect(card.locator(".sid-result")).to_contain_text("現在の公開対象ではありません")
        expect(card.get_by_role("button", name="SIDを追加", exact=True)).to_be_disabled()
        page.get_by_role("button", name="一覧を更新", exact=True).click()
        expect(page.locator(".empty-list")).to_contain_text("現在、公開対象のQualifierリーグはありません")
        seed_public_qualifier(control)
        control.commit(lambda state: state["active"].update(fetchedAt=utc_text(utc_now()-timedelta(seconds=61))))
        upstream.fail = True
        page.get_by_role("button", name="一覧を更新", exact=True).click()
        expect(page.locator("#catalog-notice")).to_contain_text("前回取得時の情報")
        expect(card.get_by_role("button", name="SIDを追加", exact=True)).to_be_disabled()
        upstream.fail = False
        control._active_retry_after = None
        page.get_by_role("button", name="一覧を更新", exact=True).click()
        expect(card.get_by_role("button", name="SIDを追加", exact=True)).to_be_enabled()
        expect(page.locator("#catalog-notice")).not_to_be_visible()
        card.get_by_label("追加するSID", exact=True).fill("recovered-sid")
        card.get_by_role("button", name="SIDを追加", exact=True).click()
        expect(card.locator(".sid-result")).to_have_text("SIDを追加しました。")
        assert errors == []

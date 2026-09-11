"""Verify proxy-to-score participant names and audit UI using isolated data and Edge."""
import argparse
import json
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from playwright.sync_api import expect, sync_playwright  # noqa: E402

from mock_servers.jbsl_web_proxy.config import Settings  # noqa: E402
from mock_servers.jbsl_web_proxy.jbsl_web_proxy_server import create_app as create_proxy  # noqa: E402
from mock_servers.jbsl_web_proxy.scoresaber import ScoreSaber  # noqa: E402
from jbsl_score.admin import create_admin  # noqa: E402
from jbsl_score.api import create_api  # noqa: E402
from jbsl_score.config import Config  # noqa: E402
from jbsl_score.security import Security  # noqa: E402
from jbsl_score.service import Service  # noqa: E402
from jbsl_score.timing import measure_operation  # noqa: E402
from jbsl_score.upstream import Identity, LeaderboardClient  # noqa: E402
from tests.conftest import Clock, login, projection  # noqa: E402
from tests.test_rankings import scored  # noqa: E402

SID = "76561198245534518"
OTHER = "76561198000000001"
LONG_NAME = "長い日本語の参加者名 " * 5 + "<img src=x onerror=alert(1)>"


class SidVerifier:
    def verify(self, ticket, provider):
        sid = SID if ticket == "mock-ticket" else OTHER
        return Identity(sid, sid, provider)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    upstream_dir = output / "upstream"
    upstream_dir.mkdir()
    clock = Clock()
    raw = projection(clock())
    raw["participants"] = [{"sid": SID}]
    raw["total_rank"] = [{"sid": OTHER, "name": LONG_NAME}]
    (upstream_dir / "leaderboard_3023.json").write_text(json.dumps(raw), encoding="utf-8")
    fixture = {key: raw[key] for key in ("isLive", "isOpen", "end", "participants", "qualifier")}
    fixture["maps"] = [{"index": i, **{key: item[key] for key in (
        "characteristic", "difficulty", "song_duration_seconds", "qualifier_attempt_limit")}}
        for i, item in enumerate(raw["maps"])]
    fixture_path = output / "fixture.json"
    fixture_path.write_text(json.dumps({"schemaVersion": 1, "leagues": {"3023": fixture}}), encoding="utf-8")
    proxy_app = create_proxy(Settings(fixture_path=fixture_path, offline_upstream_dir=upstream_dir))
    calls = []

    def profile(request):
        calls.append(str(request.url))
        assert request.url.path == "/api/v2/players/" + SID
        return httpx.Response(200, json={"id": SID, "name": "リュナン"})

    proxy_app.state.scoresaber = ScoreSaber(transport=httpx.MockTransport(profile))
    with socket.socket() as listener, TestClient(proxy_app) as proxy:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        config = Config(data_dir=output / "score-data", admin_port=port,
                        admin_public_url=f"http://127.0.0.1:{port}")
        def relay(request):
            response = proxy.get(request.url.path)
            return httpx.Response(response.status_code, content=response.content)
        service = Service(config, LeaderboardClient(config, httpx.MockTransport(relay)), SidVerifier(), clock)
        Security(service).create_admin("operator", "test-admin-password-2026")
        with TestClient(create_api(service, background=False), base_url=config.api_public_url) as api:
            assert login(api).json()["user"]["displayName"] == SID
            scored(api, sid=SID)
            assert api.get("/api/v1/auth/me").json()["user"]["displayName"] == "リュナン"
            assert login(api, other=True).json()["user"]["displayName"] == LONG_NAME
        with service.db.transaction() as c:
            c.executemany("INSERT INTO audit(occurred_at,actor,event,details_json) VALUES(?,?,?,?)",
                          [(clock(), "legacy", "legacy_entry", "{}") for _ in range(55)])
        with measure_operation():
            time.sleep(0.02)
            service.db.audit(clock(), "test", "validation_operation")
        server = uvicorn.Server(uvicorn.Config(create_admin(service), log_level="warning"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        errors = []
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if time.monotonic() > deadline:
                    raise RuntimeError("UI test server did not start")
                time.sleep(0.01)
            with sync_playwright() as p:
                browser = p.chromium.launch(channel="msedge" if sys.platform == "win32" else "chromium", headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1000}, locale="ja-JP")
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(config.admin_public_url + "/admin/")
                page.get_by_label("ユーザー名", exact=True).fill("operator")
                page.get_by_label("パスワード", exact=True).fill("test-admin-password-2026")
                page.get_by_role("button", name="ログイン", exact=True).click()
                recent = page.locator(".panel").filter(has=page.get_by_role("heading", name="最近の操作・受信ログ"))
                expect(recent.get_by_role("columnheader", name="所要時間")).to_be_visible()
                expect(recent.locator("tbody tr").first.locator("td").nth(3)).to_contain_text(" ms")
                expect(recent.locator("tbody tr").filter(has_text="legacy_entry").first.locator("td").nth(3)).to_have_text("—")
                page.screenshot(path=str(output / "overview.png"), full_page=True)
                page.get_by_role("button", name="ユーザー", exact=True).click()
                expect(page.get_by_role("cell", name="リュナン", exact=True)).to_be_visible()
                expect(page.get_by_role("cell", name=LONG_NAME, exact=True)).to_be_visible()
                assert page.locator("tbody img").count() == 0
                page.screenshot(path=str(output / "users.png"), full_page=True)
                page.get_by_label("SID または表示名", exact=True).fill("リュナン")
                page.get_by_role("button", name="検索", exact=True).click()
                expect(page.locator("tbody tr")).to_have_count(1)
                expect(page.get_by_role("cell", name=SID, exact=True)).to_be_visible()
                page.get_by_role("button", name="操作・受信ログ", exact=True).click()
                expect(page.get_by_role("columnheader", name="所要時間")).to_be_visible()
                expect(page.locator("tbody tr").filter(has_text="validation_operation").locator("td").nth(3)).to_contain_text(" ms")
                page.screenshot(path=str(output / "audit-desktop.png"))
                page.get_by_role("button", name="所要時間の説明", exact=True).click()
                expect(page.get_by_role("dialog", name="所要時間", exact=True)).to_contain_text("このイベントを記録")
                page.keyboard.press("Escape")
                page.get_by_role("button", name="次の50件を表示", exact=True).click()
                with service.db.read() as c:
                    total_audits = c.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
                expect(page.locator("tbody tr")).to_have_count(total_audits)
                page.set_viewport_size({"width": 390, "height": 844})
                page.get_by_role("columnheader", name="所要時間").first.scroll_into_view_if_needed()
                assert page.locator("tbody tr").first.bounding_box()["height"] <= 140
                page.screenshot(path=str(output / "audit-mobile.png"))
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert not errors, errors
                browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=10)
        assert calls == ["https://scoresaber.com/api/v2/players/" + SID], calls
        result = {"status": "passed", "name": "リュナン", "scoresaberRequests": len(calls),
                  "checks": ["proxy-to-score names", "SID-only user update", "cached first login", "name search",
                             "HTML as text", "overview timing", "audit timing", "legacy rows", "pagination",
                             "timing help", "mobile layout"], "javascriptErrors": errors}
        (output / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

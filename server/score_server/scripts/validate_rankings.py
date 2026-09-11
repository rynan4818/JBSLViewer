"""Exercise rankings and moderation in Edge using an isolated database and loopback listener."""

import argparse
import gzip
import json
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from playwright.sync_api import expect, sync_playwright  # noqa: E402

from jbsl_score.admin import create_admin  # noqa: E402
from jbsl_score.api import create_api  # noqa: E402
from jbsl_score.config import Config  # noqa: E402
from jbsl_score.contracts import validate_projection  # noqa: E402
from jbsl_score.security import Security  # noqa: E402
from jbsl_score.service import Service  # noqa: E402
from jbsl_score.upstream import Identity  # noqa: E402
from tests.conftest import MAP, SID, Clock, Upstream, Verifier, bsor, login  # noqa: E402
from tests.test_rankings import scored  # noqa: E402


class ValidatedUpstream(Upstream):
    def get(self, league_id):
        return validate_projection(super().get(league_id))


class SidVerifier(Verifier):
    def verify(self, ticket, provider):
        identity = super().verify(ticket, provider)
        return Identity(identity.sid, identity.sid, provider)


def check_public_rankings(browser, origin, output, errors):
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="ja-JP")
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script(
        "window.cspViolations = []; document.addEventListener('securitypolicyviolation', "
        "e => window.cspViolations.push(e.violatedDirective));"
    )
    page.goto(origin + "/admin/")
    link = page.get_by_role("link", name="ランキング表示（ログイン不要）", exact=True)
    expect(link).to_be_visible()
    page.screenshot(path=str(output / "public-rankings-login.png"), full_page=True)
    requests = []
    page.on("request", lambda request: requests.append(request) if "/admin/api/" in request.url else None)
    link.click()
    expect(page).to_have_url(origin + "/admin/rankings/")
    expect(page.locator(".ranking-panel")).to_have_count(3)
    expect(page.locator("button:not(:disabled), [role=button], dialog, aside")).to_have_count(0)
    expect(page.locator("#ranking-list thead").first).to_have_text("順位ユーザー最高スコア残回数提出日時 / 結果リプレイ")
    expect(page.locator("#ranking-replay-note")).to_contain_text("HTTPS配信")
    expect(page.get_by_text("この譜面にはランキング対象のスコアがまだありません。", exact=True)).to_be_visible()
    expect(page.locator(".ranking-metadata").filter(has_text="回数上限: 7回")).to_contain_text("曲時間: —")
    assert context.cookies() == []
    assert all(request.method == "GET" and "/admin/api/public/rankings" in request.url for request in requests)
    assert all("cookie" not in request.headers for request in requests)
    page.screenshot(path=str(output / "public-rankings-desktop.png"), full_page=True)
    selected = json.dumps([MAP["hash"], MAP["characteristic"], MAP["difficulty"]], separators=(",", ":"))
    page.get_by_label("譜面", exact=True).select_option(selected)
    expect(page.locator(".ranking-panel")).to_have_count(1)
    expect(page.locator(".ranking-metadata")).to_contain_text("回数上限: 10回")
    expect(page.locator(".ranking-metadata")).to_contain_text("曲時間: 180.125秒")
    rows = page.locator("#ranking-list tbody tr")
    expect(rows).to_have_count(3)
    assert rows.locator("td:first-child").all_text_contents() == ["1", "1", "3"]
    target = rows.filter(has_text=SID)
    expect(target.locator(".ranking-score strong")).to_have_text("115")
    expect(target.locator(".ranking-attempts")).to_have_text("8回")
    expect(target.locator(".ranking-user-name")).to_have_text("日本語プレイヤー")
    for name in ("BeatLeaderで再生", "ArcViewerで再生"):
        expect(target.get_by_role("button", name=name, exact=True)).to_be_disabled()
    expect(target.locator(".ranking-replay-actions")).to_have_text("DLBeatLeaderArcViewer")
    boxes = target.locator(".ranking-replay-action").evaluate_all(
        "nodes => nodes.map(node => { const r=node.getBoundingClientRect(); return {y:r.y, height:r.height}; })"
    )
    assert len({round(box["y"]) for box in boxes}) == 1 and max(box["height"] for box in boxes) <= 30
    with page.expect_download() as download_event:
        target.get_by_role("link", name="Replayをダウンロード", exact=True).click()
    downloaded = download_event.value
    assert downloaded.suggested_filename.endswith(".bsor.gz")
    downloaded.save_as(output / "public-replay.bsor.gz")
    assert gzip.decompress((output / "public-replay.bsor.gz").read_bytes()) == gzip.decompress(bsor())
    assert context.cookies() == []
    expect(page.locator("#ranking-list img")).to_have_count(0)
    expect(rows.filter(has_text="76561198000000002")).to_contain_text("<img src=x onerror=alert(1)>")
    page.get_by_label("譜面", exact=True).select_option("")
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.screenshot(path=str(output / "public-rankings-mobile.png"), full_page=True)
    target.first.get_by_role("button", name="ArcViewerで再生", exact=True).scroll_into_view_if_needed()
    page.screenshot(path=str(output / "public-rankings-mobile-actions.png"), full_page=True)
    page.get_by_label("リーグ", exact=True).select_option("4023")
    expect(rows).to_have_count(1)
    expect(page.locator(".ranking-score strong")).to_have_text("105")
    expect(page.locator("#ranking-map")).to_have_value("")

    # A slower previous league response must not overwrite the last selection.
    pattern = "**/admin/api/public/rankings*"
    older_data = context.request.get(origin + "/admin/api/public/rankings?leagueId=3023").json()
    held = []

    def delay_previous(route):
        if "leagueId=3023" in route.request.url:
            held.append(route)
        else:
            route.continue_()

    page.route(pattern, delay_previous)
    page.get_by_label("リーグ", exact=True).select_option("3023")
    page.get_by_label("リーグ", exact=True).select_option("4023")
    expect(rows).to_have_count(1)
    assert len(held) == 1
    held[0].fulfill(json=older_data)
    page.wait_for_load_state("networkidle")
    expect(page.locator("#ranking-league")).to_have_value("4023")
    expect(page.locator(".ranking-score strong")).to_have_text("105")
    page.unroute(pattern, delay_previous)
    page.get_by_label("リーグ", exact=True).select_option("3023")
    expect(rows).to_have_count(4)
    page.reload()
    expect(rows).to_have_count(4)
    assert page.evaluate("window.cspViolations") == []

    page.route(pattern, lambda route: route.fulfill(status=503, json={"error": {"message": "unavailable"}}))
    page.reload()
    expect(page.locator("#ranking-error")).to_contain_text("ランキングを取得できませんでした。")
    expect(page.locator(".ranking-panel")).to_have_count(0)
    expect(page.locator("#ranking-list")).to_have_attribute("aria-busy", "false")
    page.screenshot(path=str(output / "public-rankings-error-mobile.png"), full_page=True)
    page.unroute(pattern)
    page.reload()
    expect(rows).to_have_count(4)
    expect(page.locator("#ranking-error")).not_to_be_visible()
    missing = context.request.get(origin + "/admin/api/public/rankings").json()
    missing["items"][0]["replay"] = {"downloadUrl": None, "beatleaderUrl": None, "arcviewerUrl": None}
    page.route(pattern, lambda route: route.fulfill(json=missing))
    page.reload()
    expect(rows.first).to_contain_text("リプレイなし")
    expect(rows.first.locator(".ranking-replay-action")).to_have_count(0)
    page.unroute(pattern)
    page.route(pattern, lambda route: route.fulfill(json={"leagues": [], "leagueId": None, "maps": [], "items": []}))
    page.reload()
    expect(page.get_by_text("リーグの記録はまだありません。", exact=True)).to_be_visible()
    expect(page.locator("#ranking-league")).to_be_disabled()
    expect(page.locator("#ranking-map")).to_be_disabled()
    expect(page.locator("button, [role=button]")).to_have_count(0)
    page.unroute(pattern)
    page.get_by_role("link", name="ログイン画面へ", exact=True).click()
    expect(page.get_by_role("button", name="ログイン", exact=True)).to_be_visible()
    assert not context.cookies()
    context.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    config = Config(data_dir=output / "data", admin_port=port, admin_public_url=f"http://127.0.0.1:{port}")
    clock, upstream = Clock(), ValidatedUpstream()
    upstream.data["league_title"] = "JBSL ランキング検証"
    upstream.data["total_rank"] = [
        {"sid": SID, "name": "日本語プレイヤー"}, {"sid": "76561198000000001", "name": "Another Player"}
    ]
    primary = upstream.data["maps"][0]
    primary.update(title="星の軌跡", qualifier_attempt_limit=10, song_duration_seconds=180.125)
    second = {**MAP, "hash": "A" * 40}
    empty = {**MAP, "difficulty": "Expert"}
    upstream.data["maps"] += [
        {**primary, **second, "title": "Blue Horizon", "qualifier_attempt_limit": 7, "song_duration_seconds": None},
        {**primary, **empty, "title": "星の軌跡（長いタイトルの折り返しを確認する未提出の譜面）"},
    ]
    service = Service(config, upstream, SidVerifier(), clock)
    Security(service).create_admin("operator", "test-admin-password-2026")
    with TestClient(create_api(service, background=False), base_url=config.api_public_url) as api:
        login(api)
        fallback = scored(api, 90)
        clock.now += 1
        best = scored(api, 115)
        scored(api, 100, key=second)
        login(api, other=True)
        scored(api, 115, sid="76561198000000001")
        third_sid = "76561198000000002"
        upstream.data["participants"].append({"sid": third_sid})
        upstream.data["total_rank"].append({"sid": third_sid, "name": "長い日本語の表示名の折り返しを確認するプレイヤー Third <img src=x onerror=alert(1)>"})
        service.verifier.verify = lambda *args: Identity(third_sid, third_sid, "steamTicket")
        login(api)
        scored(api, 80, sid=third_sid)
        upstream.data["league_id"] = 4023
        upstream.data["league_title"] = "別リーグ"
        scored(api, 105, league=4023, sid=third_sid)

    server = uvicorn.Server(uvicorn.Config(create_admin(service), log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("Test listener failed to start")
            time.sleep(0.05)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge" if sys.platform == "win32" else "chromium", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, locale="ja-JP")
            errors, failures = [], []
            check_public_rankings(browser, config.admin_public_url, output, errors)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("response", lambda response: failures.append(f"{response.status} {response.url}") if response.status >= 500 else None)
            page.goto(config.admin_public_url + "/admin/")
            page.get_by_label("ユーザー名", exact=True).fill("operator")
            page.get_by_label("パスワード", exact=True).fill("test-admin-password-2026")
            page.get_by_role("button", name="ログイン", exact=True).click()
            page.get_by_role("heading", name="概要", exact=True).wait_for()
            page.get_by_role("button", name="ランキング", exact=True).click()
            expect(page.locator(".ranking-panel")).to_have_count(3)
            expect(page.get_by_text("この譜面にはランキング対象のスコアがまだありません。", exact=True)).to_be_visible()
            expect(page.locator(".ranking-metadata").filter(has_text="回数上限: 7回")).to_contain_text("曲時間: —")
            page.screenshot(path=str(output / "rankings-desktop.png"), full_page=True)
            selected = json.dumps([MAP["hash"], MAP["characteristic"], MAP["difficulty"]], separators=(",", ":"))
            page.get_by_label("譜面", exact=True).select_option(selected)
            expect(page.locator(".ranking-panel")).to_have_count(1)
            expect(page.locator(".ranking-metadata")).to_contain_text("回数上限: 10回")
            expect(page.locator(".ranking-metadata")).to_contain_text("曲時間: 180.125秒")
            rows = page.locator("#ranking-list tbody tr")
            expect(rows).to_have_count(3)
            assert rows.locator("td:first-child").all_text_contents() == ["1", "1", "3"]
            assert page.locator("#ranking-list img").count() == 0
            target = rows.filter(has_text=SID)
            expect(target.locator(".ranking-user-name")).to_have_text("日本語プレイヤー")
            expect(target.locator(".ranking-attempts")).to_have_text("8回")
            target.get_by_role("button", name="ユーザー・提出履歴", exact=True).click()
            expect(page.get_by_role("heading", name="SID " + SID, exact=True)).to_be_visible()
            expect(page.locator("#filter-sid")).to_have_value(SID)
            page.get_by_role("button", name="ランキングへ戻る", exact=True).click()
            expect(page.locator("#ranking-map")).to_have_value(selected)
            target.get_by_role("button", name="詳細・取消・復元", exact=True).click()
            dialog = page.locator("#submission-dialog")
            expect(dialog).to_contain_text(best)
            expect(dialog.get_by_role("link", name="Replayをダウンロード")).to_have_attribute("href", f"/admin/api/submissions/{best}/replay")
            dialog.get_by_label("操作理由", exact=True).fill("ランキングからの取消検証")
            dialog.get_by_role("button", name="このスコアを取り消す", exact=True).click()
            expect(dialog).not_to_be_visible()
            expect(target.locator("td").nth(0)).to_have_text("2")
            expect(target.locator(".ranking-score strong")).to_have_text("90")
            expect(target.locator(".ranking-attempts")).to_have_text("8回")
            expect(page.locator("#ranking-map")).to_have_value(selected)
            target.get_by_role("button", name="詳細・取消・復元", exact=True).click()
            expect(dialog).to_contain_text(fallback)
            dialog.get_by_role("button", name="閉じる", exact=True).click()
            target.get_by_role("button", name="ユーザー・提出履歴", exact=True).click()
            canceled = page.locator("tbody tr").filter(has_text="取消済み")
            canceled.get_by_role("button", name="詳細・取消・復元", exact=True).click()
            expect(dialog).to_contain_text(best)
            dialog.get_by_label("操作理由", exact=True).fill("ランキングからの復元検証")
            dialog.get_by_role("button", name="このスコアを復元する", exact=True).click()
            expect(dialog).not_to_be_visible()
            page.get_by_role("button", name="ランキングへ戻る", exact=True).click()
            expect(target.locator(".ranking-score strong")).to_have_text("115")
            target.get_by_role("button", name="1回返却", exact=True).click()
            refund = page.locator("#challenge-action-dialog")
            expect(refund).to_contain_text(SID)
            refund.get_by_label("操作理由", exact=True).fill("ランキングからの手動返却検証")
            refund.get_by_role("button", name="1回返却する", exact=True).click()
            expect(refund).not_to_be_visible()
            expect(target.get_by_text("返却済み", exact=True)).to_be_visible()
            expect(target.locator(".ranking-score strong")).to_have_text("115")
            expect(target.locator(".ranking-attempts")).to_have_text("9回")
            page.get_by_role("button", name="更新", exact=True).click()
            expect(page.locator("#ranking-map")).to_have_value(selected)
            page.get_by_label("リーグ", exact=True).select_option("4023")
            expect(page.locator("#ranking-map")).to_have_value("")
            expect(page.locator("#ranking-list tbody tr")).to_have_count(1)
            expect(page.locator("#ranking-list .ranking-score strong")).to_have_text("105")
            page.get_by_label("リーグ", exact=True).select_option("3023")
            expect(page.locator("#ranking-list tbody tr")).to_have_count(4)
            page.get_by_role("button", name="ランキングの説明", exact=True).click()
            expect(page.locator("#help-dialog")).to_be_visible()
            page.keyboard.press("Escape")
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=str(output / "rankings-mobile.png"), full_page=True)
            assert not errors and not failures, (errors, failures)
            browser.close()
        summary = {"status": "passed", "checks": ["public login link and return link", "anonymous direct navigation and reload", "public API requests without cookies", "public replay download and HTTPS prerequisite", "missing replay display; no management dialogs", "public league/map filters and stale-response protection", "public empty/error states and reload recovery", "public mobile layout and CSP", "league/map filters", "best scores and ties", "user navigation and selection retention", "cancel fallback", "restore", "refund", "replay link", "empty chart", "WEB name completion and escaping", "attempt limits and fractional/unknown duration", "remaining attempts before/after moderation and refund", "mobile layout with long title"], "consoleErrors": errors, "serverErrors": failures}
        (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()


if __name__ == "__main__":
    main()

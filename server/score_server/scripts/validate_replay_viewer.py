"""Isolated HTTPS/browser verification, optionally using the real external viewers.

Pass a public BSOR fixture and a test-only PEM certificate/key. Never uses config.json
or the production database. External playback needs browser network access.
"""

import argparse
import gzip
import json
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import uvicorn
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def seed(service, raw):
    from fastapi.testclient import TestClient
    from jbsl_score.api import create_api
    from jbsl_score.replay import decode_gzip
    from jbsl_score.upstream import Identity
    from tests.conftest import Upstream, metadata, projection

    info = decode_gzip(gzip.compress(raw), 16 * 1024**2, 64 * 1024**2).info
    key = {"hash": info.hash, "characteristic": info.mode, "difficulty": info.difficulty}
    data = projection(time.time())
    data["participants"] = [{"sid": info.player_id}]
    data["maps"] = [{**data["maps"][0], **key}]
    service.upstream = Upstream(data)

    class FixtureVerifier:
        def verify(self, ticket, provider):
            assert ticket == "public-fixture"
            return Identity(info.player_id, "Public replay validation", "steamTicket")

    service.verifier = FixtureVerifier()
    with TestClient(create_api(service, background=False), base_url=service.config.api_public_url) as api:
        response = api.post("/api/v1/auth/session", data={"ticket": "public-fixture", "provider": "steamTicket"})
        assert response.status_code == 200, response.text
        reservation = api.post("/api/v1/qualifiers/challenges", json={
            "schemaVersion": 1, "leagueId": 3023, "map": key, "clientVersion": "replay-viewer-validation",
            "gameVersion": info.game_version,
        }, headers={"Idempotency-Key": "a2678a64-412d-427c-b287-72d27ca61b74"})
        assert reservation.status_code == 201, reservation.text
        challenge = reservation.json()["challengeId"]
        result = metadata(challenge, end="clear", score=info.score)
        result.update(map=key, gameVersion=info.game_version, maxPossibleModifiedScore=info.score)
        submitted = api.put(f"/api/v1/qualifiers/challenges/{challenge}/result", files={
            "metadata": (None, json.dumps(result), "application/json"),
            "replay": ("public-fixture.bsor.gz", gzip.compress(raw), "application/gzip"),
        }, headers={"Idempotency-Key": result["clientResultId"]})
        assert submitted.status_code == 201, submitted.text
        return challenge, submitted.json()["submissionId"]


def run(args):
    from jbsl_score.__main__ import ManagedServer
    from jbsl_score.admin import create_admin
    from jbsl_score.api import create_api
    from jbsl_score.config import Config
    from jbsl_score.security import Security
    from jbsl_score.service import Service
    from tests.conftest import login_admin

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = Config(
        data_dir=output / "test-data", api_port=port(), admin_port=port(),
        ssl_certfile=str(args.cert.resolve()), ssl_keyfile=str(args.key.resolve()),
    )
    config.api_public_url = f"https://127.0.0.1:{config.api_port}"
    config.admin_public_url = f"https://127.0.0.1:{config.admin_port}"
    if (config.data_dir / "score.sqlite3").exists():
        raise ValueError("Use a new output directory for the isolated replay-viewer test")
    service = Service(config)
    challenge_id, submission_id = seed(service, args.fixture_bsor.read_bytes())
    Security(service).create_admin("operator", "test-admin-password-2026")
    servers, threads = [], []
    summary = {"external": args.external, "publicRanking": args.public, "checks": []}
    try:
        for app, listen_port in ((create_api(service, background=False), config.api_port), (create_admin(service), config.admin_port)):
            server = ManagedServer(uvicorn.Config(
                app, host="127.0.0.1", port=listen_port, ssl_certfile=config.ssl_certfile,
                ssl_keyfile=config.ssl_keyfile, access_log=False, log_level="error",
            ))
            thread = threading.Thread(target=server.run, daemon=True)
            servers.append(server)
            threads.append(thread)
            thread.start()
        deadline = time.monotonic() + 20
        while not all(server.started for server in servers):
            if time.monotonic() > deadline:
                raise RuntimeError("Local HTTPS test servers did not start")
            time.sleep(0.05)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            context = browser.new_context(ignore_https_errors=True, viewport={"width": 1440, "height": 1000}, locale="ja-JP")
            # Allow this test's loopback TLS listener; production uses a public HTTPS endpoint.
            for origin in ("https://replay.beatleader.com", "https://allpoland.github.io"):
                context.grant_permissions(["local-network-access"], origin=origin)
            if not args.external:
                for host in ("replay.beatleader.com", "allpoland.github.io"):
                    context.route(f"https://{host}/**", lambda route: route.fulfill(body="<p>Viewer navigation fixture</p>", content_type="text/html"))
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            if args.public:
                page.goto(config.admin_public_url + "/admin/rankings/")
                dialog = page.locator("#ranking-list tbody tr").filter(has_text="Public replay validation")
                action_role, capture = "link", page
                expect(dialog.locator(".ranking-replay-actions")).to_have_text("DLBeatLeaderArcViewer")
                boxes = dialog.locator(".ranking-replay-action").evaluate_all(
                    "nodes => nodes.map(node => { const r=node.getBoundingClientRect(); return {y:r.y, height:r.height}; })"
                )
                assert len({round(box["y"]) for box in boxes}) == 1 and max(box["height"] for box in boxes) <= 30
                assert context.cookies() == []
                with page.expect_download() as download_event:
                    dialog.get_by_role("link", name="Replayをダウンロード", exact=True).click()
                downloaded = download_event.value
                assert downloaded.suggested_filename == submission_id + ".bsor.gz"
                downloaded.save_as(output / "public-replay.bsor.gz")
                assert gzip.decompress((output / "public-replay.bsor.gz").read_bytes()) == args.fixture_bsor.read_bytes()
                summary["checks"].append("anonymous download matches the submitted replay")
            else:
                page.goto(config.admin_public_url + "/admin/")
                page.get_by_label("ユーザー名", exact=True).fill("operator")
                page.get_by_label("パスワード", exact=True).fill("test-admin-password-2026")
                page.get_by_role("button", name="ログイン", exact=True).click()
                page.get_by_role("button", name="Challenge・提出", exact=True).click()
                page.locator("tbody tr").filter(has_text=challenge_id).get_by_role("button", name="詳細・取消・復元", exact=True).click()
                dialog = page.get_by_role("dialog", name="提出結果", exact=True)
                action_role, capture = "button", dialog
            expect(dialog.get_by_role(action_role, name="BeatLeaderで再生", exact=True)).to_be_enabled()
            prefix = "public-rankings" if args.public else "submission"
            capture.screenshot(path=str(output / (prefix + "-desktop.png")))
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            capture.screenshot(path=str(output / (prefix + "-mobile.png")))
            if args.public:
                dialog.get_by_role("link", name="ArcViewerで再生", exact=True).scroll_into_view_if_needed()
                page.screenshot(path=str(output / "public-rankings-mobile-actions.png"))
            page.set_viewport_size({"width": 1440, "height": 1000})
            for name, host in (("BeatLeader", "replay.beatleader.com"), ("ArcViewer", "allpoland.github.io")):
                if args.viewer and name.lower() != args.viewer:
                    continue
                deliveries, console = [], []

                def record(response):
                    prefix = "/api/v1/public/replays/" if args.public else "/api/v1/replay-viewer/"
                    if response.url.startswith(config.api_public_url + prefix):
                        deliveries.append({"status": response.status, "origin": response.request.header_value("origin"),
                                           "cookie": response.request.header_value("cookie"),
                                           "cors": response.header_value("access-control-allow-origin")})

                context.on("response", record)
                with page.expect_popup() as popup_event:
                    dialog.get_by_role(action_role, name=name + "で再生", exact=True).click()
                popup = popup_event.value
                popup.on("console", lambda message: console.append(message.text))
                popup.wait_for_url(f"https://{host}/**", timeout=30000)
                assert popup.evaluate("window.opener === null")
                assert popup.evaluate("document.referrer") == ""
                if args.public:
                    query = parse_qs(urlsplit(popup.url).query)
                    replay_url = query["link" if name == "BeatLeader" else "replayURL"][0]
                    assert "/api/v1/public/replays/" + submission_id + "/" in replay_url
                    assert urlsplit(replay_url).query == "" and replay_url.endswith(".bsor")
                    assert query.get("noProxy") == (["true"] if name == "ArcViewer" else None)
                if args.external:
                    if name == "BeatLeader":
                        popup.wait_for_function(
                            "() => { const r=document.querySelector('[replay-loader]')?.components?.['replay-loader']; return r?.replay?.frames?.length > 0 && r.challenge; }",
                            timeout=90000,
                        )
                        frames = popup.evaluate("document.querySelector('[replay-loader]').components['replay-loader'].replay.frames.length")
                        assert frames > 0
                        summary["beatleaderFrames"] = frames
                        popup.locator("canvas").first.click(position={"x": 720, "y": 500})
                        popup.wait_for_function(
                            "() => { const s=document.querySelector('[song]')?.components?.song; return s?.isPlaying && (s.audio?.currentTime || s.lastCurrentTime) > 0.5; }",
                            timeout=15000,
                        )
                        summary["beatleaderPlayback"] = "playing; playback time advances"
                    else:
                        popup.goto(popup.url + "&autoPlay=true")
                        popup.wait_for_function("() => !!document.querySelector('canvas')", timeout=90000)
                        deadline = time.monotonic() + 90
                        while time.monotonic() < deadline:
                            popup.wait_for_timeout(500)
                            if any("Initialized Scoring Events for replay" in line for line in console) and any("Environment loaded." in line for line in console):
                                break
                        (output / "arcviewer-console.txt").write_text(
                            "\n".join(line for line in console if "token=" not in line), encoding="utf-8",
                        )
                        assert any("Initialized Scoring Events for replay" in line for line in console), "ArcViewer did not initialize the replay"
                        assert any("Environment loaded." in line for line in console), "ArcViewer did not load the environment"
                        # First-visit Unity canvas notice, observed at this fixed viewport.
                        popup.locator("canvas").click(position={"x": 943, "y": 750})
                        popup.wait_for_timeout(300)
                        popup.locator("canvas").click(position={"x": 720, "y": 610})
                        popup.wait_for_timeout(1500)
                        summary["arcviewerPlayback"] = "autoPlay; map, audio, replay scoring and environment loaded"
                    assert any(item["status"] == 200 and item["origin"] == item["cors"] and not item["cookie"] for item in deliveries), deliveries
                    popup.screenshot(path=str(output / (name.lower() + "-viewer.png")))
                    summary[name.lower() + "Deliveries"] = deliveries
                popup.close()
                context.remove_listener("response", record)
                summary["checks"].append(name + " button and isolated navigation")
                print(name + ": browser check passed", flush=True)
            if not args.public:
                # Exercise popup denial and server failure without sending another replay externally.
                page.evaluate("window.originalOpen=window.open; window.open=()=>null")
                dialog.get_by_role("button", name="BeatLeaderで再生", exact=True).click()
                fallback = dialog.get_by_role("link", name="再生ページを開く", exact=True)
                expect(fallback).to_be_visible()
                expect(fallback).to_have_attribute("rel", "noopener noreferrer")
                page.route("**/replay-viewer", lambda route: route.fulfill(status=503, json={"error": {"code": "test_failure", "message": "検証用の発行失敗"}}))
                dialog.get_by_role("button", name="ArcViewerで再生", exact=True).click()
                expect(dialog.locator(".replay-feedback")).to_contain_text("検証用の発行失敗")
                expect(dialog.get_by_role("button", name="ArcViewerで再生", exact=True)).to_be_enabled()
                page.unroute("**/replay-viewer")
                summary["checks"].extend(["popup fallback", "issuance failure"])
            summary["checks"].append("mobile layout")
            config.api_public_url = config.api_public_url.replace("https://", "http://")
            if args.public:
                assert context.cookies([config.admin_public_url, config.api_public_url]) == []
                page.reload()
                expect(page.locator("#ranking-replay-note")).to_contain_text("HTTPS配信")
                expect(dialog.get_by_role("link", name="Replayをダウンロード", exact=True)).to_be_visible()
            else:
                dialog.get_by_role("button", name="閉じる", exact=True).click()
                page.locator("tbody tr").filter(has_text=challenge_id).get_by_role("button", name="詳細・取消・復元", exact=True).click()
                expect(dialog.get_by_text("外部再生にはAPI公開URLのHTTPS設定が必要です。", exact=True)).to_be_visible()
            expect(dialog.get_by_role("button", name="BeatLeaderで再生", exact=True)).to_be_disabled()
            expect(dialog.get_by_role("button", name="ArcViewerで再生", exact=True)).to_be_disabled()
            summary["checks"].append("HTTPS prerequisite")
            config.api_public_url = config.api_public_url.replace("http://", "https://")
            assert not errors, errors
            browser.close()
        with httpx.Client(base_url=config.admin_public_url, verify=False, trust_env=False) as admin:
            login_admin(admin)
            detail = admin.get(f"/admin/api/submissions/{submission_id}").json()
            assert detail["replayViewerAvailable"]
        summary["status"] = "passed"
        (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Replay viewer browser validation: PASS", flush=True)
    finally:
        for server in servers:
            server.should_exit = True
        for thread in threads:
            thread.join(timeout=10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixture-bsor", type=Path, required=True)
    parser.add_argument("--cert", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--external", action="store_true")
    parser.add_argument("--public", action="store_true", help="Exercise anonymous public ranking replay actions")
    parser.add_argument("--viewer", choices=["beatleader", "arcviewer"])
    run(parser.parse_args())

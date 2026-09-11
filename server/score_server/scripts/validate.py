"""One command: Python tests, actual Viewer C# client, HTTP and browser checks."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def free_ports(count):
    sockets = []
    try:
        for _ in range(count):
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            sockets.append(sock)
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


def run(command, output, name, timeout=600):
    env = dict(os.environ)
    env["DOTNET_CLI_HOME"] = str(output / ".dotnet")
    env["DOTNET_SKIP_FIRST_TIME_EXPERIENCE"] = "1"
    env["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
    env["DOTNET_GENERATE_ASPNET_CERTIFICATE"] = "false"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    temp_dir = output / "process-temp"
    temp_dir.mkdir(exist_ok=True)
    env["TEMP"] = env["TMP"] = str(temp_dir)
    result = subprocess.run(
        command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout
    )
    (output / (name + ".log")).write_bytes(result.stdout)
    print(f"{name}: {'PASS' if result.returncode == 0 else 'FAIL'}", flush=True)
    if result.returncode:
        print(result.stdout.decode("utf-8", errors="replace"))
        raise RuntimeError(name + " failed; inspect the saved log")
    return result.stdout.decode("utf-8", errors="replace")


def challenge_control_checks(page, info, output):
    from playwright.sync_api import expect
    from jbsl_score.service import timestamp
    from tests.conftest import MAP, SID, login, reserve

    def row(challenge_id):
        return page.locator("tbody tr").filter(has_text=challenge_id)

    dialog = page.locator("#challenge-action-dialog")
    with httpx.Client(base_url=info["api"], trust_env=False, timeout=30) as player:
        login(player)

        def budget():
            response = player.get(
                f"/integration/v1/leagues/3023/users/{SID}/attempts",
                headers={"Authorization": "Bearer " + info["token"]},
            )
            response.raise_for_status()
            return next(b for b in response.json()["items"] if b["map"] == MAP)

        def check_budget(expected_used):
            current = budget()
            assert current["usedAttempts"] == expected_used
            cells = page.locator(".panel").first.locator("tbody tr").first.locator("td")
            expect(cells.nth(2)).to_have_text(str(current["usedAttempts"]))
            expect(cells.nth(3)).to_have_text(str(current["refundedAttempts"]))
            expect(cells.nth(4)).to_have_text(f"{current['remainingAttempts']} / {current['attemptLimit']}")

        expect(page.get_by_role("heading", name="SID " + SID, exact=True)).to_be_visible()
        before = budget()["usedAttempts"]
        target = page.locator("tbody tr").filter(has=page.get_by_role("button", name="1回返却", exact=True)).first
        challenge_id = target.locator("td").first.inner_text().splitlines()[-1]
        target.get_by_role("button", name="1回返却", exact=True).click()
        expect(dialog).to_be_visible()
        expect(dialog.get_by_role("checkbox")).not_to_be_visible()
        dialog.get_by_label("操作理由", exact=True).fill("   ")
        dialog.get_by_role("button", name="1回返却する", exact=True).click()
        expect(dialog).to_be_visible()
        assert budget()["usedAttempts"] == before
        dialog.get_by_label("操作理由", exact=True).fill("自動ブラウザ検証: 提出済みの手動返却")
        dialog.get_by_role("button", name="1回返却する", exact=True).click()
        expect(dialog).not_to_be_visible()
        expect(row(challenge_id).get_by_role("button", name="1回返却", exact=True)).to_have_count(0)
        expect(row(challenge_id).locator(".challenge-actions").get_by_text("返却済み", exact=True)).to_be_visible()
        check_budget(before - 1)
        page.screenshot(path=str(output / "admin-manual-refund.png"), full_page=True)

        # Reuse the returned attempt to exercise a reserved and then a started challenge.
        for refund in (False, True):
            reservation = reserve(player)
            assert reservation.status_code == 201, reservation.text
            challenge_id = reservation.json()["challengeId"]
            if refund:
                response = player.post(
                    f"/api/v1/qualifiers/challenges/{challenge_id}/started",
                    json={"schemaVersion": 1, "actualMap": MAP, "gameMode": "Solo", "practice": False,
                          "submissionAllowed": True, "startedAtClient": timestamp(time.time())},
                )
                assert response.status_code == 200, response.text
            page.get_by_role("button", name="更新", exact=True).click()
            target = row(challenge_id)
            expect(target).to_contain_text("プレイ中" if refund else "予約済み")
            target.get_by_role("button", name="強制終了", exact=True).click()
            expect(dialog.get_by_role("checkbox", name="同時に1回返却する")).not_to_be_checked()
            dialog.get_by_role("button", name="チャレンジ操作の説明", exact=True).click()
            expect(page.get_by_role("dialog", name="チャレンジ操作", exact=True)).to_be_visible()
            page.keyboard.press("Escape")
            expect(dialog).to_be_visible()
            if refund:
                dialog.get_by_role("checkbox", name="同時に1回返却する").check()
            dialog.get_by_label("操作理由", exact=True).fill("自動ブラウザ検証: 強制終了" + ("と返却" if refund else "のみ"))
            if refund:
                dialog.screenshot(path=str(output / "admin-force-end-dialog.png"))
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                dialog.screenshot(path=str(output / "admin-force-end-mobile.png"))
                page.set_viewport_size({"width": 1440, "height": 1000})
            dialog.get_by_role("button", name="強制終了して1回返却する" if refund else "強制終了する", exact=True).click()
            expect(dialog).not_to_be_visible()
            expect(row(challenge_id).get_by_text("強制終了", exact=True)).to_be_visible()
            expect(row(challenge_id).get_by_role("button", name="強制終了", exact=True)).to_have_count(0)
            check_budget(before - 1 if refund else before)
            late = player.put(f"/api/v1/qualifiers/challenges/{challenge_id}/result", content=b"late result")
            assert late.status_code == 409 and late.json()["error"]["code"] == "admin_force_ended"
            if not refund:
                row(challenge_id).get_by_role("button", name="1回返却", exact=True).click()
                dialog.get_by_label("操作理由", exact=True).fill("自動ブラウザ検証: 強制終了後に返却")
                dialog.get_by_role("button", name="1回返却する", exact=True).click()
                expect(dialog).not_to_be_visible()
                check_budget(before - 1)
        page.screenshot(path=str(output / "admin-challenge-controls.png"), full_page=True)


def browser_checks(info, output):
    from playwright.sync_api import expect, sync_playwright
    from documentation_checks import public_documentation, settings_help, submission_help, watch_documentation

    with sync_playwright() as p:
        # Installed Edge works on Windows without downloading a browser engine.
        browser = p.chromium.launch(channel="msedge" if os.name == "nt" else "chromium", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="ja-JP")
        documentation_errors, external_requests = watch_documentation(context)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(info["admin"] + "/admin/")
        expect(page.get_by_role("button", name="ログイン", exact=True)).to_be_visible()
        public_documentation(context, page, output)
        page.get_by_label("ユーザー名", exact=True).fill("operator")
        page.get_by_label("パスワード", exact=True).fill("test-admin-password-2026")
        page.get_by_role("button", name="ログイン", exact=True).click()
        expect(page.get_by_role("heading", name="概要", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="最近のChallenge")).to_be_visible()
        page.screenshot(path=str(output / "admin-overview.png"), full_page=True)
        page.get_by_role("button", name="サーバ設定", exact=True).click()
        grace = page.get_by_role("spinbutton", name="終了後の提出猶予（秒）", exact=False)
        expect(grace).to_have_value("300")
        settings_help(page, output)
        assert grace.bounding_box()["width"] >= 250, "Settings inputs are squeezed horizontally"
        grace.fill("420")
        page.get_by_role("checkbox", name="開始前の失敗", exact=False).check()
        page.get_by_role("button", name="設定を保存", exact=True).click()
        expect(page.get_by_role("status")).to_contain_text("設定を保存しました")
        page.reload()
        page.get_by_role("button", name="サーバ設定", exact=True).click()
        expect(page.get_by_role("spinbutton", name="終了後の提出猶予（秒）", exact=False)).to_have_value("420")
        expect(page.get_by_role("checkbox", name="開始前の失敗", exact=False)).to_be_checked()
        page.screenshot(path=str(output / "admin-settings.png"), full_page=True)
        page.get_by_role("button", name="ユーザー", exact=True).click()
        page.get_by_role("button", name="提出状況を確認", exact=True).first.click()
        expect(page.get_by_role("heading", name="ユーザーのChallenge・提出")).to_be_visible()
        # C# integration creates two ranked replay results and one metadata-only result.
        page.get_by_role("button", name="詳細・取消・復元", exact=True).first.click()
        expect(page.get_by_role("dialog")).to_be_visible()
        submission_help(page)
        page.get_by_role("dialog", name="提出結果", exact=True).get_by_label("操作理由", exact=True).fill("自動ブラウザ検証: 取消")
        page.get_by_role("button", name="このスコアを取り消す", exact=True).click()
        expect(page.get_by_role("status")).to_contain_text("スコアを取り消しました")
        page.get_by_role("button", name="詳細・取消・復元", exact=True).first.click()
        page.get_by_role("dialog", name="提出結果", exact=True).get_by_label("操作理由", exact=True).fill("自動ブラウザ検証: 復元")
        page.get_by_role("button", name="このスコアを復元する", exact=True).click()
        expect(page.get_by_role("status")).to_contain_text("スコアを復元しました")
        challenge_control_checks(page, info, output)
        page.screenshot(path=str(output / "admin-user.png"), full_page=True)
        page.get_by_role("button", name="操作・受信ログ", exact=True).click()
        expect(page.get_by_role("cell", name="score_cancel", exact=True)).to_be_visible()
        expect(page.get_by_role("cell", name="score_restore", exact=True)).to_be_visible()
        expect(page.get_by_role("cell", name="challenge_force_ended", exact=True)).to_have_count(2)
        expect(page.get_by_role("cell", name="attempt_refunded", exact=True).first).to_be_visible()
        page.set_viewport_size({"width": 390, "height": 844})
        page.get_by_role("button", name="サーバ設定", exact=True).click()
        mobile_grace = page.get_by_role("spinbutton", name="終了後の提出猶予（秒）", exact=False)
        expect(mobile_grace).to_have_value("420")
        assert mobile_grace.bounding_box()["width"] >= 250
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(output / "admin-mobile.png"), full_page=True)
        page.get_by_role("button", name="ログアウト", exact=True).click()
        expect(page.get_by_role("button", name="ログイン", exact=True)).to_be_visible()
        assert not errors, errors
        assert not documentation_errors, documentation_errors
        assert not external_requests, external_requests
        context.close()
        browser.close()
    return {
        "login": "passed",
        "settings_persist": "passed",
        "user_history": "passed",
        "cancel_restore": "passed",
        "force_end": "passed (reserved, started, late result rejected)",
        "manual_refund": "passed (submitted, force-ended, combined, budget refreshed)",
        "challenge_confirmation": "passed (reason required, nested help, mobile)",
        "audit": "passed",
        "logout": "passed",
        "javascript_errors": errors,
        "swagger_ui": "passed (all documented operations, offline, read only)",
        "contextual_help": "passed (settings, keyboard, nested dialog, focus restoration)",
        "operator_guide": "passed (7 figures, interactive deadline example, mobile)",
        "documentation_external_requests": external_requests,
    }


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-unit", action="store_true", help="Only rerun HTTP and browser tests")
    parser.add_argument("--skip-browser", action="store_true", help="Report browser verification as skipped")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = (
        args.output or ROOT / "validation" / "latest" / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:6])
    ).resolve()
    output.mkdir(parents=True, exist_ok=True)
    summary = {"status": "running", "output": str(output)}
    process = None
    logfile = None
    try:
        if not args.skip_unit:
            run(
                [
                    sys.executable,
                    "-m",
                    "ruff",
                    "check",
                    "jbsl_score",
                    "tests",
                    "scripts",
                    "integration_client.py",
                    "--no-cache",
                ],
                output,
                "lint",
            )
            test_temp = output / ("pytest-" + uuid4().hex)
            assert test_temp.parent == output and not test_temp.exists()
            run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "--basetemp=" + str(test_temp),
                    "--junitxml=" + str(output / "python-tests.xml"),
                ],
                output,
                "python-tests",
            )
        run(
            ["dotnet", "build", "validation/ViewerContract.csproj", "--nologo", "--verbosity", "quiet"],
            output,
            "csharp-build",
        )
        core = run(["dotnet", "validation/bin/Debug/net8.0/ViewerContract.dll"], output, "csharp-core")
        api_port, admin_port, web_port = free_ports(3)
        info_path = output / "test-connection.json"
        logfile = (output / "http-server.log").open("wb")
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            kwargs["startupinfo"] = startup
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tests.live_environment",
                "--data",
                str(output / "test-data"),
                "--api-port",
                str(api_port),
                "--admin-port",
                str(admin_port),
                "--web-port",
                str(web_port),
                "--info",
                str(info_path),
            ],
            cwd=ROOT,
            stdout=logfile,
            stderr=subprocess.STDOUT,
            **kwargs,
        )
        with httpx.Client(trust_env=False, timeout=1) as client:
            deadline = time.monotonic() + 30
            while True:
                if process.poll() is not None:
                    raise RuntimeError("Test server exited during startup")
                try:
                    if client.get(f"http://127.0.0.1:{api_port}/readyz").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() > deadline:
                    raise RuntimeError("Test server did not become ready")
                time.sleep(0.1)
        info = json.loads(info_path.read_text(encoding="utf-8"))
        http_result = run(
            ["dotnet", "validation/bin/Debug/net8.0/ViewerContract.dll", "integration", info["api"], info["web"]],
            output,
            "csharp-http",
        )
        if not args.skip_browser:
            summary["browser"] = browser_checks(info, output)
            print("browser: PASS", flush=True)
            run(
                [sys.executable, "scripts/validate_rankings.py", "--output", str(output / "rankings")],
                output,
                "rankings-browser",
            )
            summary["rankings"] = json.loads((output / "rankings" / "summary.json").read_text(encoding="utf-8"))
            print("rankings: PASS", flush=True)
        else:
            summary["browser"] = "skipped"
            summary["rankings"] = "skipped"
        with httpx.Client(trust_env=False, timeout=30) as client:
            feed = client.get(
                info["api"] + "/integration/v1/changes", headers={"Authorization": "Bearer " + info["token"]}
            )
            assert feed.status_code == 200
            assert len(feed.json()["items"]) >= 3
            (output / "integration-feed.json").write_text(
                json.dumps(feed.json(), indent=2, ensure_ascii=False), encoding="utf-8"
            )
            assert client.get(info["api"] + "/admin/api/state").status_code == 404
            assert client.get(info["admin"] + "/api/v1/auth/me").status_code == 404
        from jbsl_score.maintenance import backup, restore_backup, verify_database
        from jbsl_score.config import Config
        from jbsl_score.service import Service

        service = Service(Config(data_dir=output / "test-data"))
        summary["database"] = verify_database(service.db.path)
        saved = backup(service, "validation")
        summary["restore"] = restore_backup(
            service.config.data_dir / "backups" / saved["file"], output / "restored-data"
        )
        summary["csharp_core"] = next(line for line in core.splitlines() if line.startswith("ALL PASSED"))
        summary["csharp_http"] = next(line for line in http_result.splitlines() if line.startswith("ALL PASSED"))
        summary["status"] = "passed"
        from production_smoke import production_smoke

        summary["production_launcher"] = production_smoke(output / "production-launcher")
    except BaseException as error:
        summary["status"] = "failed"
        summary["error"] = str(error)
        raise
    finally:
        if process is not None and process.poll() is None:
            process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
            try:
                process.wait(timeout=35)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if logfile:
            logfile.close()
        (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Validation report: " + str(output / "summary.json"), flush=True)


if __name__ == "__main__":
    main()

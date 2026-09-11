import builtins
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from mock_servers.jbsl_web_proxy import __main__ as cli
from mock_servers.jbsl_web_proxy import admin_auth
from mock_servers.jbsl_web_proxy.admin_auth import AdminAuth, COOKIE_NAME, SESSION_SECONDS
from mock_servers.jbsl_web_proxy.admin_server import make_apps
from mock_servers.jbsl_web_proxy.control import Control
from mock_servers.jbsl_web_proxy.errors import ApiProblem
from .test_admin import ADMIN_PASSWORD, ADMIN_USER, HEADERS, PublicFixture, login_admin


@pytest.fixture
def auth(tmp_path):
    store = AdminAuth(tmp_path / "admin_auth.sqlite3", clock=lambda: 1800000000.0)
    store.set_admin(ADMIN_USER, ADMIN_PASSWORD)
    return store


@pytest.fixture
def anonymous_console(tmp_path):
    public = PublicFixture()
    control = Control(tmp_path, transport=httpx.MockTransport(public))
    control.auth.set_admin(ADMIN_USER, ADMIN_PASSWORD)
    admin, proxy = make_apps(control)
    with TestClient(admin, headers=HEADERS) as client, TestClient(proxy) as viewer:
        yield client, viewer, control, public


def test_every_management_route_requires_login_before_side_effects(anonymous_console):
    client, viewer, control, public = anonymous_console
    before = control.path.read_bytes()
    checked = set()
    for route in client.app.routes:
        if not route.path.startswith("/admin/api/") or route.path == "/admin/api/login":
            continue
        path = route.path.replace("{league_id}", "3023")
        for method in route.methods:
            response = client.request(method, path, **({"json": {}} if method not in {"GET", "HEAD"} else {}))
            assert response.status_code == 401, (method, path, response.text)
            assert response.headers["cache-control"] == "no-store"
            checked.add(route.path)
    assert {"/admin/api/settings", "/admin/api/leagues/{league_id}", "/admin/api/me", "/admin/api/logs"} <= checked
    for path in ("/admin/%61pi/overview", "/admin/api/overview/", "/admin/api/new-route", "/admin/api"):
        assert client.get(path).status_code == 401
    assert control.path.read_bytes() == before
    assert not public.requests and not public.beatsaver_requests and not control.drafts and not control.log.read()
    for path in ("/admin/", "/static/index.html", "/guide", "/healthz"):
        assert client.get(path).status_code == 200
    assert viewer.get("/leaderboard/api/3023").status_code == 200
    for path in ("/docs", "/openapi.json", "/__mock__/state", "/healthz"):
        assert viewer.get(path).status_code == 200
    for path in ("/data/admin_auth.sqlite3", "/static/admin_auth.sqlite3", "/admin_auth.py"):
        assert client.get(path).status_code == 404
        assert viewer.get(path).status_code == 404


def test_login_cookie_csrf_logout_and_replay(anonymous_console):
    client, _, control, _ = anonymous_console
    response = login_admin(client)
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Path=/admin" in cookie and "SameSite=strict" in cookie
    assert "Max-Age=28800" in cookie and "Secure" not in cookie
    token = client.cookies[COOKIE_NAME]
    info = response.json()
    assert client.get("/admin/api/me").json() == info
    assert client.get("/admin/api/overview").status_code == 200
    before = control.path.read_bytes()
    for csrf in ("", "invalid", "x" * 300):
        rejected = client.post("/admin/api/logs/clear", json={}, headers={"X-CSRF-Token": csrf})
        assert rejected.status_code == 403 and rejected.json()["error"]["code"] == "csrf_rejected"
    assert control.path.read_bytes() == before
    assert client.post("/admin/api/logout", json={}, headers={"X-CSRF-Token": ""}).status_code == 403
    assert client.get("/admin/api/me").status_code == 200
    response = client.post("/admin/api/logout", json={})
    assert response.status_code == 204 and not response.content
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert COOKIE_NAME not in client.cookies
    assert client.get("/admin/api/me").status_code == 401
    assert client.get("/admin/api/overview", headers={"Cookie": f"{COOKIE_NAME}={token}"}).status_code == 401


def test_cookie_from_score_server_or_a_forged_session_is_not_accepted(anonymous_console):
    client, _, _, _ = anonymous_console
    login_admin(client)
    token = client.cookies[COOKIE_NAME]
    client.cookies.clear()
    for cookie in (f"jbslq_admin={token}", f"{COOKIE_NAME}=forged", f"{COOKIE_NAME}={'x' * 1024}"):
        assert client.get("/admin/api/me", headers={"Cookie": cookie}).status_code == 401


def test_login_requires_origin_header_and_json_checks(anonymous_console):
    client, _, _, _ = anonymous_console
    credentials = {"username": ADMIN_USER, "password": ADMIN_PASSWORD}
    for headers in ({"Origin": "https://evil.invalid"}, {"Host": "evil.invalid"},
                    {"X-JBSL-Admin": ""}, {"Sec-Fetch-Site": "cross-site"}):
        assert client.post("/admin/api/login", json=credentials, headers=headers).status_code == 403
    assert client.post("/admin/api/login", content=json.dumps(credentials)).status_code == 415
    assert client.post("/admin/api/login", json={**credentials, "unexpected": True}).status_code == 400
    assert client.post("/admin/api/login", json={**credentials, "password": "x" * 5000}).status_code == 413
    assert not client.cookies


def test_failed_login_is_generic_and_forwarded_headers_do_not_bypass_limit(anonymous_console):
    client, _, control, _ = anonymous_console
    for index in range(5):
        response = client.post("/admin/api/login", json={"username": ADMIN_USER if index % 2 else "unknown", "password": "wrong"},
                               headers={"X-Forwarded-For": f"192.0.2.{index}", "CF-Connecting-IP": f"192.0.2.{index}"})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_login"
        assert response.json()["error"]["message"] == "ユーザー名またはパスワードが違います。"
    limited = client.post("/admin/api/login", json={"username": ADMIN_USER, "password": ADMIN_PASSWORD})
    assert limited.status_code == 429 and limited.headers["retry-after"] == "60"
    assert not client.cookies and not control.log.read()


def test_credentials_are_hashed_and_sessions_persist_expire_and_reset(auth):
    token, info = auth.login(ADMIN_USER, ADMIN_PASSWORD, "client")
    restarted = AdminAuth(auth.path, clock=auth.clock)
    assert restarted.authenticate(token, info["csrfToken"], True) == info
    with sqlite3.connect(auth.path) as db:
        encoded = db.execute("SELECT password_hash FROM admin_users").fetchone()[0]
        stored_token = db.execute("SELECT token_hash FROM admin_sessions").fetchone()[0]
    assert encoded.startswith("scrypt$16384$") and ADMIN_PASSWORD not in encoded
    assert token not in auth.path.read_bytes().decode("utf-8", errors="ignore")
    assert stored_token == admin_auth.token_hash(token)
    assert admin_auth.password_hash(ADMIN_PASSWORD) != encoded
    restarted.clock = lambda: auth.clock() + SESSION_SECONDS
    with pytest.raises(ApiProblem, match="管理者ログイン") as expired:
        restarted.authenticate(token)
    assert expired.value.status == 401
    auth.set_admin(ADMIN_USER, "replacement-password")
    with pytest.raises(ApiProblem):
        auth.authenticate(token)
    with pytest.raises(ApiProblem):
        auth.login(ADMIN_USER, ADMIN_PASSWORD, "client")
    assert auth.login(ADMIN_USER, "replacement-password", "client")[1]["username"] == ADMIN_USER


def test_password_reset_racing_login_does_not_issue_a_session(auth, monkeypatch):
    verify = admin_auth.password_matches
    def reset_during_verification(password, encoded):
        matched = verify(password, encoded)
        auth.set_admin(ADMIN_USER, "replacement-password")
        return matched
    monkeypatch.setattr(admin_auth, "password_matches", reset_during_verification)
    with pytest.raises(ApiProblem) as result:
        auth.login(ADMIN_USER, ADMIN_PASSWORD, "client")
    assert result.value.status == 401
    with sqlite3.connect(auth.path) as db:
        assert db.execute("SELECT COUNT(*) FROM admin_sessions").fetchone()[0] == 0


def test_session_rotation_limit_and_csrf_are_per_session(auth):
    sessions = [auth.login(ADMIN_USER, ADMIN_PASSWORD, f"client-{i}") for i in range(6)]
    with pytest.raises(ApiProblem):
        auth.authenticate(sessions[0][0])
    for token, info in sessions[1:]:
        assert auth.authenticate(token, info["csrfToken"], True) == info
    with pytest.raises(ApiProblem) as wrong_csrf:
        auth.authenticate(sessions[-1][0], sessions[-2][1]["csrfToken"], True)
    assert wrong_csrf.value.status == 403
    token, _ = auth.login(ADMIN_USER, ADMIN_PASSWORD, "client-6", sessions[-1][0])
    with pytest.raises(ApiProblem):
        auth.authenticate(sessions[-1][0])
    assert auth.authenticate(token)["username"] == ADMIN_USER


def test_concurrent_login_limit_and_next_window(auth):
    def attempt(_):
        try:
            auth.login("unknown", "wrong", "one-client")
        except ApiProblem as exc:
            return exc.status
    with ThreadPoolExecutor(max_workers=6) as pool:
        assert sorted(pool.map(attempt, range(6))) == [401, 401, 401, 401, 401, 429]
    auth.clock = lambda: 1800000060.0
    assert auth.login(ADMIN_USER, ADMIN_PASSWORD, "one-client")[1]["username"] == ADMIN_USER


@pytest.mark.parametrize("username,password", [("", ADMIN_PASSWORD), (" admin", ADMIN_PASSWORD),
    ("a" * 65, ADMIN_PASSWORD), (ADMIN_USER, "short"), (ADMIN_USER, "x" * 257)])
def test_bad_admin_setup_does_not_replace_credentials(auth, username, password):
    with pytest.raises(ValueError):
        auth.set_admin(username, password)
    assert auth.login(ADMIN_USER, ADMIN_PASSWORD, "client")[1]["username"] == ADMIN_USER


def test_cli_initialization_and_reset_use_hidden_interactive_input(tmp_path, monkeypatch):
    directory = tmp_path / "custom-data"
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(builtins, "input", lambda prompt: ADMIN_USER)
    passwords = iter([ADMIN_PASSWORD, ADMIN_PASSWORD, "replacement-password", "replacement-password"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: next(passwords))
    cli.main(["init", "--data-dir", str(directory)])
    auth = AdminAuth(directory / "admin_auth.sqlite3")
    token, _ = auth.login(ADMIN_USER, ADMIN_PASSWORD, "client")
    cli.main(["init", "--data-dir", str(directory)])  # Must not prompt or change an existing account.
    assert auth.authenticate(token)["username"] == ADMIN_USER
    cli.main(["set-admin", ADMIN_USER, "--data-dir", str(directory)])
    with pytest.raises(ApiProblem):
        auth.authenticate(token)
    assert auth.login(ADMIN_USER, "replacement-password", "client")[1]["username"] == ADMIN_USER
    assert not (directory / "control.json").exists()


def test_cli_missing_terminal_or_cancelled_password_never_creates_an_admin(tmp_path, monkeypatch):
    auth = AdminAuth(tmp_path / "auth.sqlite3")
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    with pytest.raises(RuntimeError, match="interactive terminal"):
        cli.configure_admin(auth)
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(builtins, "input", lambda prompt: ADMIN_USER)
    passwords = iter([ADMIN_PASSWORD, "different-password"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: next(passwords))
    with pytest.raises(ValueError, match="do not match"):
        cli.configure_admin(auth)
    assert not auth.has_admin()


def test_default_cli_still_passes_existing_launch_options(tmp_path, monkeypatch):
    captured = []
    async def serve(args):
        captured.append(args)
    monkeypatch.setattr(cli, "serve", serve)
    cli.main(["--data-dir", str(tmp_path), "--offline", "--proxy-port", "19080", "--admin-port", "19764"])
    assert captured[0].command == "run" and captured[0].offline
    assert (captured[0].api_port, captured[0].admin_port, captured[0].data_dir) == (19080, 19764, tmp_path)

import gzip
import json
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from jbsl_score.database import token_hash
from jbsl_score.maintenance import backup, restore_backup, verify_database
from jbsl_score.replay_viewer import REPLAY_PATH, TOKEN_SECONDS, VIEWERS
from jbsl_score.service import Service

from .conftest import SID, bsor, login, login_admin, metadata, reserve, submit
from .test_documentation import check_response


@pytest.fixture
def replay_server(server):
    api, admin, service, upstream, clock, _ = server
    login(api)
    submission = submit(api, metadata(reserve(api).json()["challengeId"], end="clear"), bsor())
    assert submission.status_code == 201
    login_admin(admin)
    # ASGI tests use an HTTPS origin without opening a real TLS listener.
    service.config.api_public_url = "https://scores.example.test"
    service.config.trusted_proxy_ips = "127.0.0.1"
    with TestClient(api.app, base_url=service.config.api_public_url) as viewer:
        yield viewer, admin, service, clock, submission.json()["submissionId"], api, upstream


def issue(admin, submission_id, viewer="beatleader"):
    return admin.post(f"/admin/api/submissions/{submission_id}/replay-viewer", json={"viewer": viewer})


def replay_url(response, viewer="beatleader"):
    assert response.status_code == 200, response.text
    return parse_qs(urlsplit(response.json()["viewerUrl"]).query)[VIEWERS[viewer][2]][0]


@pytest.mark.parametrize("viewer_name", VIEWERS)
def test_exact_saved_replay_and_scoped_url(replay_server, viewer_name):
    viewer, admin, service, clock, submission_id, _, _ = replay_server
    response = issue(admin, submission_id, viewer_name)
    url = replay_url(response, viewer_name)
    parts = urlsplit(url)
    outer = urlsplit(response.json()["viewerUrl"])
    assert outer.scheme + "://" + outer.netloc == VIEWERS[viewer_name][0]
    assert outer.path == VIEWERS[viewer_name][1]
    assert parse_qs(outer.query).get("noProxy") == (["true"] if viewer_name == "arcviewer" else None)
    assert parts.scheme + "://" + parts.netloc == service.config.api_public_url
    assert parts.path == REPLAY_PATH.format(submission_id=submission_id, player_id=SID)
    token = parse_qs(parts.query)["token"][0]
    assert len(token) == 43
    with service.db.read() as c:
        saved = c.execute("SELECT * FROM replay_viewer_tokens").fetchone()
        assert saved["token_hash"] == token_hash(token)
        assert saved["expires_at"] == clock() + TOKEN_SECONDS
        assert token not in json.dumps(dict(saved))
        assert token not in json.dumps([dict(r) for r in c.execute("SELECT * FROM audit")])
    for headers in ({}, {"Origin": VIEWERS[viewer_name][0], "Sec-Fetch-Site": "cross-site"}):
        downloaded = viewer.get(url, headers=headers)
        assert downloaded.status_code == 200
        assert downloaded.content == gzip.decompress(bsor())
        assert downloaded.headers["content-type"] == "application/octet-stream"
        assert downloaded.headers["cache-control"] == "no-store"
        assert downloaded.headers.get("access-control-allow-origin") == headers.get("Origin")
        assert "access-control-allow-credentials" not in downloaded.headers
        assert "set-cookie" not in downloaded.headers
    original = admin.get(f"/admin/api/submissions/{submission_id}/replay")
    assert original.status_code == 200 and gzip.decompress(original.content) == gzip.decompress(bsor())
    assert viewer.get(url.replace(submission_id, submission_id.upper())).content == gzip.decompress(bsor())
    assert replay_url(issue(admin, submission_id, viewer_name), viewer_name) != url
    doc = admin.get("/admin/openapi.json").json()
    check_response(doc, "/admin/api/submissions/{submission_id}/replay-viewer", "post", response)
    detail = admin.get(f"/admin/api/submissions/{submission_id}")
    assert detail.json()["replayViewerAvailable"] is True
    check_response(doc, "/admin/api/submissions/{submission_id}", "get", detail)


@pytest.mark.parametrize("change", ["missing", "wrong", "duplicate", "submission", "player", "expired", "logout"])
def test_token_is_required_and_bound_to_submission_and_session(replay_server, change):
    viewer, admin, _, clock, submission_id, _, _ = replay_server
    url = replay_url(issue(admin, submission_id))
    parts = urlsplit(url)
    if change == "missing":
        url = urlunsplit(parts._replace(query=""))
    elif change == "wrong":
        url = urlunsplit(parts._replace(query=urlencode({"token": "x" * 43})))
    elif change == "duplicate":
        url += "&" + parts.query
    elif change == "submission":
        url = url.replace(submission_id, str(uuid4()))
    elif change == "player":
        url = url.replace(SID, "76561198000000001")
    elif change == "expired":
        clock.now += TOKEN_SECONDS
    elif change == "logout":
        assert admin.post("/admin/api/logout").status_code == 204
    response = viewer.get(url, headers={"Origin": VIEWERS["beatleader"][0]})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "replay_viewer_token_invalid"
    assert "access-control-allow-origin" not in response.headers


def test_issue_requires_admin_csrf_https_and_replay(replay_server):
    viewer, admin, service, _, submission_id, api, _ = replay_server
    path = f"/admin/api/submissions/{submission_id}/replay-viewer"
    assert viewer.post(path, json={"viewer": "beatleader"}).status_code == 404
    assert admin.post(path, json={"viewer": "beatleader"}, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    for body in ({}, [], {"viewer": []}, {"viewer": "other"}, {"viewer": "beatleader", "url": "https://evil.test"}):
        assert admin.post(path, json=body).status_code == 400
    assert issue(admin, str(uuid4())).status_code == 404
    login(viewer)
    missing = submit(viewer, metadata(reserve(viewer).json()["challengeId"])).json()["submissionId"]
    assert issue(admin, missing).status_code == 404
    service.config.api_public_url = "http://127.0.0.1:18081"
    assert issue(admin, submission_id).status_code == 409
    assert admin.get(f"/admin/api/submissions/{submission_id}").json()["replayViewerAvailable"] is False
    assert admin.post("/admin/api/logout").status_code == 204
    assert issue(admin, submission_id).status_code == 401


def test_origin_preflight_host_and_method_boundaries(replay_server):
    viewer, admin, _, _, submission_id, _, _ = replay_server
    url = replay_url(issue(admin, submission_id))
    origin = VIEWERS["beatleader"][0]
    headers = {"Origin": origin, "Access-Control-Request-Method": "GET"}
    response = viewer.options(url, headers=headers)
    assert response.status_code == 204 and response.content == b""
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-methods"] == "GET"
    assert "access-control-allow-credentials" not in response.headers
    for untrusted in (VIEWERS["arcviewer"][0], "https://evil.test", origin + ".evil.test", "null"):
        response = viewer.get(url, headers={"Origin": untrusted})
        assert response.status_code == 403
        assert "access-control-allow-origin" not in response.headers
    for changes in ({"Access-Control-Request-Method": "POST"}, {"Access-Control-Request-Headers": "Authorization"}):
        assert viewer.options(url, headers={**headers, **changes}).status_code == 403
    assert viewer.options(urlsplit(url).path, headers=headers).status_code == 401
    for method in ("POST", "PUT", "DELETE", "HEAD"):
        assert viewer.request(method, url, headers={"Origin": origin}).status_code == 403
    assert viewer.get(url, headers={"Host": "evil.test", "Origin": origin}).status_code == 400
    assert viewer.get(url.replace("https://", "http://"), headers={"Origin": origin}).status_code == 403
    for path in ("/api/v1/auth/me", "/integration/v1/changes", urlsplit(url).path + "/extra"):
        assert viewer.get(path, headers={"Origin": origin}).status_code == 403
    assert admin.get("/admin/api/me", headers={"Origin": origin}).status_code == 403


def test_expiry_cleanup_session_replacement_and_backup_restore(replay_server, tmp_path):
    viewer, admin, service, clock, submission_id, _, upstream = replay_server
    first = replay_url(issue(admin, submission_id))
    with service.db.transaction() as c:
        c.execute("UPDATE admin_sessions SET expires_at=?", (clock() + 10,))
    response = issue(admin, submission_id)
    with service.db.read() as c:
        assert c.execute("SELECT MAX(expires_at) FROM replay_viewer_tokens").fetchone()[0] == clock() + TOKEN_SECONDS
    from jbsl_score.contracts import parse_utc
    assert parse_utc(response.json()["expiresAt"]).timestamp() == clock() + 10
    login_admin(admin)
    assert viewer.get(first).status_code == 401
    fresh = replay_url(issue(admin, submission_id))
    saved_backup = backup(service)
    target = tmp_path / "restored"
    restore_backup(service.config.data_dir / "backups" / saved_backup["file"], target)
    assert verify_database(target / "score.sqlite3")["results"] == 1
    import sqlite3
    with sqlite3.connect(target / "score.sqlite3") as c:
        assert c.execute("SELECT COUNT(*) FROM replay_viewer_tokens").fetchone()[0] == 0
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    clock.now += TOKEN_SECONDS
    service.sweep()
    with service.db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM replay_viewer_tokens").fetchone()[0] == 0
    assert viewer.get(fresh).status_code == 401
    # A real v2 database has no replay-viewer table. Preserve existing receipts on migration.
    with service.db.transaction() as c:
        c.execute("DROP TABLE replay_viewer_tokens")
        c.execute("PRAGMA user_version=2")
    upgraded = Service(service.config, upstream, service.verifier, clock)
    with upgraded.db.read() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 3
        assert c.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM replay_blobs").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM replay_viewer_tokens").fetchone()[0] == 0


def test_decompression_and_request_limits(replay_server):
    viewer, admin, service, clock, submission_id, _, _ = replay_server
    url = replay_url(issue(admin, submission_id))
    raw_limit = service.config.expanded_replay_limit
    service.config.expanded_replay_limit = 8
    assert viewer.get(url).status_code == 413
    service.config.expanded_replay_limit = raw_limit
    for _ in range(29):
        assert viewer.get(url).status_code == 200
    limited = viewer.get(url)
    assert limited.status_code == 429 and limited.headers["retry-after"] == "60"
    clock.now += 60
    assert viewer.get(url).status_code == 200

import gzip
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from jbsl_score import reports
from jbsl_score.replay_viewer import PUBLIC_DOWNLOAD_PATH, PUBLIC_REPLAY_PATH, VIEWERS

from .conftest import MAP, SID, bsor, login, login_admin, metadata, reserve, submit
from .test_documentation import check_response
from .test_rankings import scored

PUBLIC = "/admin/api/public/rankings"


def download(submission_id):
    return PUBLIC_DOWNLOAD_PATH.format(submission_id=submission_id)


def delivery(submission_id, sid=SID):
    return PUBLIC_REPLAY_PATH.format(submission_id=submission_id, player_id=sid)


@pytest.fixture
def public_server(server):
    api, admin, service, upstream, clock, _ = server
    upstream.data["maps"][0]["qualifier_attempt_limit"] = 10
    login(api)
    best = scored(api, 110)
    service.config.api_public_url = "https://scores.example.test"
    with TestClient(api.app, base_url=service.config.api_public_url) as guest:
        yield guest, admin, service, upstream, clock, best


@pytest.mark.parametrize("cookie", [None, "expired-admin-token"])
def test_guest_download_and_both_viewers_get_exact_ranked_replay(public_server, cookie):
    guest, admin, service, upstream, _, best = public_server
    if cookie:
        admin.cookies.set("jbslq_admin", cookie)
    calls = upstream.calls
    with service.db.read() as c:
        compressed = c.execute("SELECT gzip_data FROM replay_blobs WHERE result_id=?", (best,)).fetchone()[0]
    response = admin.get(PUBLIC)
    check_response(admin.get("/admin/openapi.json").json(), PUBLIC, "get", response)
    replay = response.json()["items"][0]["replay"]
    assert replay["downloadUrl"] == download(best)
    saved = admin.get(replay["downloadUrl"])
    assert saved.status_code == 200 and saved.content == compressed
    assert saved.headers["content-type"] == "application/gzip"
    assert saved.headers["content-disposition"] == f'attachment; filename="{best}.bsor.gz"'
    assert saved.headers["cache-control"] == "no-store" and "set-cookie" not in saved.headers
    for viewer_name, (origin, path, parameter) in VIEWERS.items():
        outer = urlsplit(replay[viewer_name + "Url"])
        assert outer.scheme + "://" + outer.netloc == origin and outer.path == path
        query = parse_qs(outer.query)
        assert query.get("noProxy") == (["true"] if viewer_name == "arcviewer" else None)
        replay_url = query[parameter][0]
        assert replay_url == service.config.api_public_url + delivery(best)
        for headers in ({}, {"Origin": origin, "Sec-Fetch-Site": "cross-site"}):
            result = guest.get(replay_url, headers=headers)
            assert result.status_code == 200 and result.content == gzip.decompress(compressed)
            assert result.headers["content-type"] == "application/octet-stream"
            assert result.headers["cache-control"] == "no-store"
            assert result.headers.get("access-control-allow-origin") == headers.get("Origin")
            assert "access-control-allow-credentials" not in result.headers
            assert "set-cookie" not in result.headers
    assert guest.get(delivery(best.upper())).content == gzip.decompress(compressed)
    assert not guest.cookies and upstream.calls == calls
    with service.db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM admin_sessions").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM replay_viewer_tokens").fetchone()[0] == 0


def test_best_updates_ties_and_moderation_recheck_old_links(public_server):
    guest, admin, _, _, clock, old = public_server
    login(guest)
    clock.now += 1
    best = scored(guest, 115)
    clock.now += 1
    tied = scored(guest, 115)
    guest.cookies.clear()
    assert admin.get(download(old)).status_code == guest.get(delivery(old)).status_code == 404
    assert admin.get(download(tied)).status_code == guest.get(delivery(tied)).status_code == 404
    assert admin.get(PUBLIC).json()["items"][0]["replay"]["downloadUrl"] == download(best)
    login_admin(admin)
    for action, version, selected, rejected in (("cancel", 0, tied, best), ("restore", 1, best, tied)):
        assert admin.post(f"/admin/api/submissions/{best}/moderate", json={
            "action": action, "version": version, "reason": "公開Replayの確認",
        }).status_code == 200
        assert admin.get(PUBLIC).json()["items"][0]["replay"]["downloadUrl"] == download(selected)
        assert admin.get(download(selected)).status_code == guest.get(delivery(selected)).status_code == 200
        assert admin.get(download(rejected)).status_code == guest.get(delivery(rejected)).status_code == 404
    assert admin.post("/admin/api/logout").status_code == 204
    assert guest.get(delivery(best)).status_code == 200


def test_same_time_ties_select_the_same_submission_as_ranking(public_server):
    guest, admin, _, _, _, first = public_server
    login(guest)
    second = scored(guest, 110)
    guest.cookies.clear()
    selected, rejected = sorted([first, second])
    assert admin.get(PUBLIC).json()["items"][0]["replay"]["downloadUrl"] == download(selected)
    assert guest.get(delivery(selected)).status_code == 200
    assert guest.get(delivery(rejected)).status_code == 404


def test_league_map_player_and_historical_scope(public_server):
    guest, admin, service, upstream, _, best = public_server
    other_sid = "76561198000000001"
    other_map = {**MAP, "difficulty": "Expert"}
    upstream.data["maps"].append({**upstream.data["maps"][0], **other_map})
    login(guest, other=True)
    other_player = scored(guest, 115, sid=other_sid)
    login(guest)
    other_chart = scored(guest, 115, key=other_map)
    upstream.data["league_id"] = 4023
    other_league = scored(guest, 115, league=4023)
    guest.cookies.clear()
    with service.db.transaction() as c:
        c.execute("DELETE FROM league_cache WHERE league_id=3023")
    for submission_id, sid in ((best, SID), (other_player, other_sid), (other_chart, SID), (other_league, SID)):
        assert admin.get(download(submission_id)).status_code == 200
        assert guest.get(delivery(submission_id, sid)).status_code == 200
        assert guest.get(delivery(submission_id, "999999999")).status_code == 404
    assert len(admin.get(PUBLIC).json()["items"]) == 3
    assert len(admin.get(PUBLIC, params={"leagueId": 4023}).json()["items"]) == 1


def test_missing_invalid_and_unranked_replays(public_server):
    guest, admin, service, _, _, best = public_server
    login(guest)
    unranked = submit(guest, metadata(reserve(guest).json()["challengeId"], end="quit"), bsor()).json()["submissionId"]
    guest.cookies.clear()
    with service.db.transaction() as c:
        c.execute("DELETE FROM replay_blobs WHERE result_id=?", (best,))
    assert admin.get(PUBLIC).json()["items"][0]["replay"] == {
        "downloadUrl": None, "beatleaderUrl": None, "arcviewerUrl": None,
    }
    for submission_id in (best, unranked, str(uuid4())):
        assert admin.get(download(submission_id)).status_code == guest.get(delivery(submission_id)).status_code == 404
    assert guest.get(delivery(best, "not-a-player")).status_code == 404
    assert admin.get(download("invalid")).status_code == guest.get(delivery("invalid")).status_code == 400


def test_http_allows_download_and_disables_external_links(server):
    api, admin, *_ = server
    login(api)
    best = scored(api)
    links = admin.get(PUBLIC).json()["items"][0]["replay"]
    assert links == {"downloadUrl": download(best), "beatleaderUrl": None, "arcviewerUrl": None}
    assert admin.get(links["downloadUrl"]).status_code == 200


def test_cors_preflight_and_listener_boundaries(public_server):
    guest, admin, _, _, _, best = public_server
    for origin, _, _ in VIEWERS.values():
        headers = {"Origin": origin, "Access-Control-Request-Method": "GET"}
        response = guest.options(delivery(best), headers=headers)
        assert response.status_code == 204 and not response.content
        assert response.headers["access-control-allow-origin"] == origin
        assert response.headers["access-control-allow-methods"] == "GET"
        assert response.headers["vary"] == "Origin"
        assert "access-control-allow-credentials" not in response.headers
        assert guest.options(delivery(str(uuid4())), headers=headers).status_code == 404
        for change in ({"Access-Control-Request-Method": "POST"}, {"Access-Control-Request-Headers": "Authorization"}):
            assert guest.options(delivery(best), headers={**headers, **change}).status_code == 403
        for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD"):
            assert guest.request(method, delivery(best), headers={"Origin": origin}).status_code == 403
        for path in ("/api/v1/auth/me", "/integration/v1/changes", delivery(best) + "/extra"):
            assert guest.get(path, headers={"Origin": origin}).status_code == 403
        assert admin.get(download(best), headers={"Origin": origin}).status_code == 403
    for origin in ("https://evil.test", "https://replay.beatleader.com.evil.test", "null"):
        response = guest.get(delivery(best), headers={"Origin": origin})
        assert response.status_code == 403 and "access-control-allow-origin" not in response.headers
    assert guest.options(delivery(best)).status_code == 403
    assert guest.get(delivery(best), headers={"Host": "evil.test"}).status_code == 400
    assert guest.get("http://scores.example.test" + delivery(best)).status_code == 403
    assert guest.get(download(best)).status_code == admin.get(delivery(best)).status_code == 404
    assert admin.get(f"/admin/api/submissions/{best}/replay").status_code == 401
    assert guest.get(f"/api/v1/replay-viewer/{best}/{SID}.bsor").status_code == 401
    assert admin.post(f"/admin/api/submissions/{best}/replay-viewer", json={"viewer": "beatleader"}).status_code == 401


def test_limits_apply_across_public_endpoints(public_server):
    guest, admin, service, _, clock, best = public_server
    service.config.expanded_replay_limit = 8
    assert guest.get(delivery(best)).status_code == 413
    service.config.expanded_replay_limit = 64 * 1024**2
    for index in range(119):
        response = admin.get(download(best)) if index % 2 else guest.get(delivery(best))
        assert response.status_code == 200
    for client, path in ((guest, delivery(best)), (admin, download(best))):
        limited = client.get(path)
        assert limited.status_code == 429 and limited.headers["retry-after"] == "60"
    clock.now += 60
    assert guest.get(delivery(best)).status_code == 200
    service.config.compressed_replay_limit = 8
    assert guest.get(delivery(best)).status_code == 413


def test_eligibility_and_blob_use_one_read_snapshot(public_server, monkeypatch):
    guest, _, service, _, _, best = public_server
    original = reports.leaderboard_rows

    def cancel_after_selection(c, league_id):
        rows = original(c, league_id)
        with service.db.transaction() as writer:
            writer.execute("UPDATE results SET canceled=1 WHERE id=?", (best,))
        return rows

    monkeypatch.setattr(reports, "leaderboard_rows", cancel_after_selection)
    assert guest.get(delivery(best)).status_code == 200
    assert guest.get(delivery(best)).status_code == 404


def test_public_replay_contract(public_server):
    guest, admin, _, _, _, best = public_server
    doc = admin.get("/admin/openapi.json").json()
    for path, method, media in ((PUBLIC_DOWNLOAD_PATH, "get", "application/gzip"),
                               (PUBLIC_REPLAY_PATH, "get", "application/octet-stream"),
                               (PUBLIC_REPLAY_PATH, "options", None)):
        operation = doc["paths"][path][method]
        assert operation["security"] == [] and "429" in operation["responses"]
        if media:
            assert operation["responses"]["200"]["content"][media]["schema"]["format"] == "binary"
    check_response(doc, PUBLIC_DOWNLOAD_PATH, "get", admin.get(download(str(uuid4()))), 404)
    check_response(doc, PUBLIC_REPLAY_PATH, "get", guest.get(delivery(best, "999")), 404)

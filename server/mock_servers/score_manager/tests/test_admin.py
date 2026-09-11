import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mock_servers.score_manager.admin_server import create_app
from mock_servers.score_manager.control import Behavior, Control, SettingsView
from mock_servers.score_manager.score_manager_server import create_app as score_app
from mock_servers.score_manager.errors import ApiProblem
from .conftest import MAP_A, FakeLeaderboardClient, authenticate, fixture_projections, metadata, reserve, result_files, valid_bsor
from mock_servers.score_manager.schemas import parse_utc

HEADERS = {"X-JBSL-Admin": "1"}


@pytest.fixture
def console(tmp_path):
    control = Control(tmp_path)
    upstream = FakeLeaderboardClient(fixture_projections())
    control.score_app = score_app(SettingsView(control), upstream, control=control)
    with TestClient(create_app(control), headers=HEADERS) as admin, TestClient(control.score_app) as score:
        yield admin, score, control, upstream


def behavior(admin, **changes):
    data = admin.get("/admin/api/overview").json()
    data["behavior"].update(changes)
    response = admin.put("/admin/api/settings", json={"behavior": data["behavior"], "generation": data["generation"]})
    assert response.status_code == 200, response.text
    return response


def submit(score, *, ranked=False, end_type="preflight_rejected"):
    reserved = reserve(score, str(uuid4()))
    assert reserved.status_code == 201, reserved.text
    challenge = reserved.json()["challengeId"]
    if ranked:
        started = score.post(f"/api/v1/qualifiers/challenges/{challenge}/started", json={
            "schemaVersion": 1, "actualMap": MAP_A, "gameMode": "Solo", "practice": False,
            "submissionAllowed": True, "startedAtClient": "2030-01-01T00:00:00Z"})
        assert started.status_code == 200
    meta = metadata(challenge, str(uuid4()), ranked=ranked, end_type=end_type)
    response = score.put(f"/api/v1/qualifiers/challenges/{challenge}/result",
        headers={"Idempotency-Key": meta["clientResultId"]}, files=result_files(meta, valid_bsor() if ranked else None))
    assert response.status_code == 201, response.text
    return challenge, response.json(), meta


def test_independent_admin_has_no_relay_controls_or_db_side_effects(console):
    admin, score, control, _ = console
    for path in ("/admin/", "/guide", "/static/app.js", "/static/inspector.js", "/static/help.js", "/healthz"):
        assert admin.get(path).status_code == 200
    assert admin.get("/admin/api/leagues").status_code == 404
    assert score.get("/admin/").status_code == 404
    state = admin.get("/admin/api/overview").json()
    assert set(state["urls"]) == {"score", "admin"}
    assert state["urls"]["score"].endswith(":18082") and state["urls"]["admin"].endswith(":18765")
    assert "leagues" not in control.snapshot() and "proxy_fault" not in state["behavior"]
    for path in ("results", "challenges", "budgets", "audit"):
        assert admin.get("/admin/api/" + path).json()["total"] == 0
    assert score.get("/docs-assets/vendor/swagger-ui/swagger-ui-bundle.js").status_code == 200


def test_score_admin_guards_local_operations(console):
    admin, *_ = console
    assert admin.post("/admin/api/logs/clear", json={}, headers={"X-JBSL-Admin": ""}).status_code == 403
    assert admin.post("/admin/api/logs/clear", json={}, headers={"Origin": "http://127.0.0.1:18764"}).status_code == 403
    assert admin.get("/admin/api/results", headers={"Host": "evil.invalid"}).status_code == 403
    assert admin.post("/admin/api/logs/clear", content="{}").status_code == 415


def test_results_detail_preserves_null_metadata_replay_and_relationship(console):
    admin, score, control, _ = console
    authenticate(score)
    challenge, result, meta = submit(score)
    _, ranked, _ = submit(score, ranked=True, end_type="clear")
    page = admin.get("/admin/api/results?ranking=invalid&end_type=preflight_rejected&league_id=3023").json()
    assert page["total"] == 1 and page["items"][0]["modified_score"] is None
    detail = admin.get("/admin/api/results/" + result["submissionId"]).json()
    assert detail["challenge"]["id"] == challenge
    assert detail["result"]["metadata"] == meta and detail["result"]["response"] == result
    assert detail["replay"] is None and detail["challenge"]["effective_status"] == "submitted"
    assert [event["event_type"] for event in detail["events"]] == ["reserved", "submitted"]
    valid = admin.get("/admin/api/results/" + ranked["submissionId"]).json()
    assert valid["replay"]["fileExists"] and valid["replay"]["byteCount"] > 0
    assert valid["result"]["valid_for_ranking"] == 1
    counts = admin.get("/admin/api/state").json()
    assert counts["rankedResults"] == counts["unrankedResults"] == 1
    budgets = admin.get("/admin/api/budgets").json()
    assert budgets["total"] == 1 and budgets["items"][0]["used_attempts"] == 2
    assert "id_hash" not in json.dumps(detail)


def test_filters_pagination_and_unknown_records(console):
    admin, score, *_ = console
    authenticate(score)
    first, *_ = submit(score)
    second, *_ = submit(score)
    for page in (1, 2):
        result = admin.get(f"/admin/api/challenges?page_size=1&page={page}").json()
        assert result["total"] == 2 and len(result["items"]) == 1
    assert admin.get("/admin/api/challenges?page_size=1&page=3").json()["items"] == []
    assert admin.get("/admin/api/challenges", params={"q": first[:16]}).json()["total"] == 1
    for query in ("%", "_", "' OR 1=1 --", "000123"):
        assert admin.get("/admin/api/challenges", params={"q": query}).json()["total"] == 0
    assert admin.get("/admin/api/results?sid=000123").json()["total"] == 0
    for path in ("results/no-such-result", "challenges/no-such-challenge"):
        assert admin.get("/admin/api/" + path).status_code == 404
    for query in ("page_size=101", "page=0", "status=bogus", "league_id=-1"):
        assert admin.get("/admin/api/challenges?" + query).status_code == 422


def test_deadline_view_is_read_only_and_matches_equality_policy(console, monkeypatch):
    admin, score, control, _ = console
    import mock_servers.score_manager.control as controls
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(controls, "utc_now", lambda: now)
    authenticate(score)
    reserved = reserve(score).json()
    challenge = reserved["challengeId"]
    now = parse_utc(reserved["resultAcceptUntil"])
    detail = admin.get("/admin/api/challenges/" + challenge).json()
    assert detail["challenge"]["effective_status"] == "reserved"
    behavior(admin, result_deadline_equal_is_accepted=False)
    detail = admin.get("/admin/api/challenges/" + challenge).json()
    assert detail["challenge"]["effective_status"] == "abandoned"
    assert detail["challenge"]["status"] == "reserved"
    assert admin.get("/admin/api/challenges?status=abandoned").json()["total"] == 1
    with control.score_app.state.db.connect() as db:
        assert db.execute("SELECT status FROM challenges").fetchone()[0] == "reserved"


def test_operational_timeout_is_visible_before_league_deadline(console, monkeypatch):
    admin, score, _, _ = console
    import mock_servers.score_manager.control as controls
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(controls, "utc_now", lambda: now)
    behavior(admin, challenge_timeout_seconds=10)
    authenticate(score)
    challenge = reserve(score).json()["challengeId"]
    now += timedelta(seconds=10)
    detail = admin.get("/admin/api/challenges/" + challenge).json()["challenge"]
    assert detail["effective_status"] == "abandoned" and detail["status"] == "reserved"
    assert parse_utc(detail["operationalTimeoutAt"]) == now


def test_fault_scope_recovery_audit_and_secret_free_logs(console):
    admin, score, control, _ = console
    behavior(admin, score_fault="authentication_required", score_fault_route="result", score_delay_ms=5)
    authenticate(score)
    assert score.get("/api/v1/auth/me").status_code == 200
    assert score.put(f"/api/v1/qualifiers/challenges/{uuid4()}/result").status_code == 401
    behavior(admin, score_fault="none", score_delay_ms=0)
    challenge = reserve(score).json()["challengeId"]
    response = score.put(f"/api/v1/qualifiers/challenges/{challenge}/result?ticket=SECRET", json={})
    assert response.status_code >= 400
    audit = admin.get("/admin/api/audit").json()
    rejected = next(r for r in audit["items"] if r["event_type"] == "result_rejected")
    assert rejected["details"]["requestId"] == response.headers["x-request-id"]
    assert "SECRET" not in json.dumps(admin.get("/admin/api/logs").json())
    admin.post("/admin/api/logs/clear", json={})
    assert admin.get("/admin/api/logs").json()["items"] == []
    assert admin.get("/admin/api/audit").json()["total"] == audit["total"]


def test_hot_settings_persist_and_do_not_change_ownership(console):
    admin, score, control, _ = console
    authenticate(score)
    challenge = reserve(score).json()["challengeId"]
    behavior(admin, stub_sid="000123", result_grace_seconds=420)
    assert score.get("/api/v1/auth/me").json()["user"]["sid"] == "76561198000000000"
    admin.post("/admin/api/actions/expire-sessions", json={})
    assert score.get("/api/v1/auth/me").status_code == 401
    assert authenticate(score).json()["user"]["sid"] == "000123"
    assert admin.get("/admin/api/challenges/" + challenge).json()["challenge"]["sid"] == "76561198000000000"
    assert Control(control.data_dir).snapshot()["behavior"]["result_grace_seconds"] == 420


def test_request_snapshot_stays_stable_across_hot_save(console):
    _, _, control, _ = console
    async def check():
        token = control.context.set(control.snapshot())
        view = SettingsView(control)
        try:
            control.save_behavior(Behavior(result_grace_seconds=500, upstream_base_url="http://127.0.0.1:19000"), 1)
            assert await asyncio.to_thread(lambda: view.result_grace_seconds) == 300
            assert view.upstream_base_url == "http://127.0.0.1:18080"
        finally:
            control.context.reset(token)
        assert view.result_grace_seconds == 500
    asyncio.run(check())


def test_upstream_change_does_not_use_previous_source_cache(console):
    admin, score, _, upstream = console
    authenticate(score)
    params = {"leagueId": 3023, **MAP_A}
    assert score.get("/api/v1/qualifiers/status", params=params).json()["eligible"]
    upstream.error = ApiProblem(503, "upstream_unavailable", "offline")
    # Fresh cache is usable for the same upstream.
    assert score.get("/api/v1/qualifiers/status", params=params).status_code == 200
    behavior(admin, upstream_base_url="http://127.0.0.1:19000")
    assert score.get("/api/v1/qualifiers/status", params=params).status_code == 503


@pytest.mark.parametrize("change", [{"upstream_base_url": "http://remote.invalid"}, {"upstream_base_url": "https://user:secret@example.com"},
    {"upstream_base_url": "http://127.0.0.1:18082"}, {"upstream_base_url": "http://127.0.0.1:123456"},
    {"metadata_limit": 0}, {"cache_stale_seconds": 10}, {"stub_sid": " a "}, {"score_delay_ms": -1}, {"proxy_fault": "none"}])
def test_invalid_settings_are_atomic(console, change):
    admin, _, control, _ = console
    before = control.path.read_bytes()
    data = admin.get("/admin/api/overview").json()
    data["behavior"].update(change)
    response = admin.put("/admin/api/settings", json={"generation": data["generation"], "behavior": data["behavior"]})
    assert response.status_code == 422
    assert control.path.read_bytes() == before


def test_conflicting_setting_save_is_rejected(console):
    admin, *_ = console
    data = admin.get("/admin/api/overview").json()
    body = {"generation": data["generation"], "behavior": data["behavior"]}
    assert admin.put("/admin/api/settings", json=body).status_code == 200
    assert admin.put("/admin/api/settings", json=body).status_code == 409

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.testclient import TestClient

from jbsl_score import timing
from jbsl_score.contracts import parse_utc
from jbsl_score.database import Database
from jbsl_score.http import Guard, install_errors
from jbsl_score.maintenance import backup
from jbsl_score.reports import audit

from .conftest import bsor, login, login_admin, metadata, reserve, submit
from .test_admin_challenges import operate, start


def test_flow_success_rejection_and_admin_events_have_duration_and_request_id(server):
    api, admin, service, _, clock, _ = server
    responses = {"authentication_succeeded": login(api), "admin_login_succeeded": login_admin(admin)}
    responses["reserved"] = reserved = reserve(api)
    challenge_id = reserved.json()["challengeId"]
    responses["started"] = start(api, challenge_id, clock)
    responses["submitted"] = submitted = submit(api, metadata(challenge_id, "clear"), bsor())
    result_id = submitted.json()["submissionId"]
    responses["score_cancel"] = admin.post(f"/admin/api/submissions/{result_id}/moderate",
                                            json={"action": "cancel", "version": 0, "reason": "Test reason"})
    responses["attempt_refunded"] = operate(admin, challenge_id, "refund")
    settings = admin.get("/admin/api/settings").json()
    responses["settings_updated"] = admin.put("/admin/api/settings", json=settings)
    responses["backup_created"] = admin.post("/admin/api/backups", json={})
    responses["request_rejected"] = api.get("/api/v1/auth/me", headers={"Host": "forbidden.example"})
    assert responses["request_rejected"].status_code == 400
    events = admin.get("/admin/api/audit", params={"limit": 100}).json()["items"]
    for event, response in responses.items():
        assert response.status_code < 400 or event == "request_rejected", response.text
        matched = [row for row in events if row["event"] == event and row["requestId"] == response.headers["X-Request-ID"]]
        assert len(matched) == 1, event
        assert type(matched[0]["elapsedMs"]) is float and matched[0]["elapsedMs"] >= 0
        assert matched[0]["details"]["elapsedMs"] == matched[0]["elapsedMs"]
    assert timing.current_operation.get() is None


def test_background_expiry_and_backup_have_independent_operation_timing(server):
    api, _, service, _, clock, _ = server
    login(api)
    reserved = reserve(api).json()
    clock.now = parse_utc(reserved["resultAcceptUntil"]).timestamp() + 1
    service.sweep()
    backup(service)
    rows = audit(service, {"limit": "100"})["items"]
    for event in ("abandoned", "backup_created"):
        row = next(r for r in rows if r["event"] == event)
        assert row["elapsedMs"] >= 0 and row["requestId"] is None
    assert timing.current_operation.get() is None


def test_measured_and_legacy_audits_survive_database_reopen(server, monkeypatch):
    _, _, service, _, clock, _ = server
    now = [100.0]
    monkeypatch.setattr(timing, "time", SimpleNamespace(monotonic=lambda: now[0]))
    details = {"reason": "unchanged input"}
    with timing.measure_operation(request_id="measured"):
        now[0] += 0.1234
        with timing.measure_operation():
            service.db.audit(clock(), "tester", "measured", details=details)
    assert details == {"reason": "unchanged input"} and timing.current_operation.get() is None
    with service.db.transaction() as c:
        c.execute("INSERT INTO audit(occurred_at,actor,event,details_json) VALUES(?,?,?,?)",
                  (clock(), "tester", "legacy", json.dumps({"reason": "old entry"})))
    service.db = Database(service.db.path)
    rows = audit(service, {"actor": "tester", "limit": "1"})
    assert rows["items"][0]["event"] == "legacy" and rows["items"][0]["elapsedMs"] is None
    next_page = audit(service, {"actor": "tester", "before": str(rows["nextCursor"]), "limit": "1"})
    measured = next_page["items"][0]
    assert measured["requestId"] == "measured" and measured["elapsedMs"] == 123.4
    assert measured["details"] == {"reason": "unchanged input", "elapsedMs": 123.4}


def test_operation_context_resets_on_failure_and_wall_clock_changes_do_not_affect_it(server, monkeypatch):
    _, _, service, _, clock, _ = server
    now = [100.0]
    monkeypatch.setattr(timing, "time", SimpleNamespace(monotonic=lambda: now[0]))
    with pytest.raises(RuntimeError), timing.measure_operation():
        clock.now -= 10000
        now[0] += 0.025
        service.db.audit(clock(), "tester", "clock_adjusted")
        raise RuntimeError("failed operation")
    assert timing.current_operation.get() is None
    assert audit(service, {"actor": "tester"})["items"][0]["elapsedMs"] == 25.0


def test_parallel_http_and_threadpool_audits_keep_their_own_request_timing(server):
    _, _, service, _, _, _ = server
    app = FastAPI()
    app.add_middleware(Guard, service=service, kind="api")
    install_errors(app, service)

    @app.get("/timing/{marker}")
    async def record(marker: str):
        operation = timing.current_operation.get()
        await asyncio.sleep(0.02)
        await run_in_threadpool(service.db.audit, service.clock(), marker, "parallel_timing")
        assert timing.current_operation.get() is operation
        return {"requestId": operation.request_id}

    with TestClient(app, base_url=service.config.api_public_url) as client, ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda i: client.get(f"/timing/{i}"), range(8)))
    ids = set()
    for marker, response in enumerate(responses):
        row = audit(service, {"actor": str(marker)})["items"][0]
        assert row["requestId"] == response.json()["requestId"] == response.headers["X-Request-ID"]
        assert row["elapsedMs"] >= 15
        ids.add(row["requestId"])
    assert len(ids) == 8 and timing.current_operation.get() is None


def test_unexpected_exception_keeps_timing_after_guard_unwinds(server):
    _, _, service, _, _, _ = server
    app = FastAPI()
    app.add_middleware(Guard, service=service, kind="api")
    install_errors(app, service)

    @app.get("/unexpected")
    async def fail():
        await asyncio.sleep(0.02)
        raise RuntimeError("test-only failure")

    with TestClient(app, base_url=service.config.api_public_url, raise_server_exceptions=False) as client:
        response = client.get("/unexpected")
    assert response.status_code == 500
    row = audit(service, {"actor": "anonymous"})["items"][0]
    assert row["details"]["code"] == "internal_error" and row["elapsedMs"] >= 15
    assert row["requestId"] == response.json()["error"]["requestId"]

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from jbsl_score.maintenance import verify_database
from jbsl_score.service import Service, timestamp

from .conftest import MAP, SID, bsor, login, login_admin, metadata, reserve, submit
from .test_rules import policy


def operate(admin, challenge_id, action="force-end", refund=False, reason=" 運営判断による再挑戦 "):
    body = {"reason": reason}
    if action == "force-end":
        body["refundAttempt"] = refund
    return admin.post(f"/admin/api/challenges/{challenge_id}/{action}", json=body)


def start(api, challenge_id, clock):
    return api.post(
        f"/api/v1/qualifiers/challenges/{challenge_id}/started",
        json={"schemaVersion": 1, "actualMap": MAP, "gameMode": "Solo", "practice": False,
              "submissionAllowed": True, "startedAtClient": timestamp(clock())},
    )


def accounting(service):
    with service.db.read() as c:
        return dict(c.execute("SELECT used,total FROM budgets").fetchone())


@pytest.mark.parametrize("started", [False, True])
@pytest.mark.parametrize("refund", [False, True])
def test_force_end_stops_admission_and_releases_active_slot(server, started, refund):
    api, admin, service, _, clock, _ = server
    policy(service, max_active_per_user=1, challenge_timeout_seconds=5, refund_conditions=["abandoned"])
    login(api)
    login_admin(admin)
    key = str(uuid4())
    original = reserve(api, key)
    challenge_id = original.json()["challengeId"]
    if started:
        assert start(api, challenge_id, clock).status_code == 200
    assert reserve(api).status_code == 409
    response = operate(admin, challenge_id, refund=refund)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "challengeId": challenge_id, "status": "abandoned", "abandonedReason": "admin_force_ended",
        "attemptRefunded": refund, "refundReason": "admin_manual" if refund else None,
    }
    assert reserve(api, key).content == original.content
    for late in (start(api, challenge_id, clock), submit(api, metadata(challenge_id))):
        assert late.status_code == 409
        assert late.json()["error"]["code"] == "admin_force_ended"
        assert late.json()["error"]["retryable"] is False
    # Replays must never upgrade an earlier force-end to a refund.
    assert operate(admin, challenge_id, refund=not refund).json() == response.json()
    clock.now += 5
    service.sweep()
    assert accounting(service) == {"used": 1 - int(refund), "total": 1}
    counts = admin.get("/admin/api/state").json()["counts"]
    assert counts["reserved"] == counts["started"] == 0
    entry = admin.get("/admin/api/challenges").json()["items"][0]
    assert entry["abandonedReason"] == "admin_force_ended"
    events = admin.get("/admin/api/audit", params={"challengeId": challenge_id}).json()["items"]
    ended = [e for e in events if e["event"] == "challenge_force_ended"]
    assert len(ended) == 1
    assert ended[0]["actor"] == "admin:operator"
    assert ended[0]["details"]["reason"] == "運営判断による再挑戦"
    assert ended[0]["details"]["before"]["status"] == ("started" if started else "reserved")
    assert ended[0]["details"]["after"] == response.json()
    next_reservation = reserve(api)
    assert next_reservation.status_code == 201
    assert next_reservation.json()["attemptNumber"] == 2
    assert verify_database(service.db.path)["challenges"] == 2


@pytest.mark.parametrize("state", ["ranked", "metadata", "canceled", "abandoned", "forced"])
def test_manual_refund_preserves_results_and_updates_readers(server, state):
    api, admin, service, _, clock, token = server
    policy(service, refund_conditions=[], challenge_timeout_seconds=5 if state == "abandoned" else 0)
    login(api)
    login_admin(admin)
    challenge_id = reserve(api).json()["challengeId"]
    receipt = None
    if state in ("ranked", "metadata", "canceled"):
        ranked = state != "metadata"
        data = metadata(challenge_id, "clear" if ranked else "preflight_rejected")
        replay = bsor() if ranked else None
        receipt = submit(api, data, replay)
        assert receipt.status_code == 201
        result_id = receipt.json()["submissionId"]
        result_path = f"/admin/api/submissions/{result_id}"
        if state == "canceled":
            assert admin.post(result_path + "/moderate", json={"action": "cancel", "version": 0, "reason": "確認"}).status_code == 200
        original = admin.get(result_path).json()
    elif state == "abandoned":
        clock.now += 5
        service.sweep()
    else:
        assert operate(admin, challenge_id).status_code == 200

    response = operate(admin, challenge_id, "refund")
    assert response.status_code == 200, response.text
    assert response.json()["attemptRefunded"] is True
    assert response.json()["refundReason"] == "admin_manual"
    assert response.json()["status"] == ("submitted" if receipt is not None else "abandoned")
    assert accounting(service) == {"used": 0, "total": 1}
    assert operate(admin, challenge_id, "refund", reason="別の理由").json() == response.json()
    for path, client, headers in (
        (f"/admin/api/users/{SID}/attempts", admin, {}),
        (f"/integration/v1/leagues/3023/users/{SID}/attempts", api, {"Authorization": "Bearer " + token}),
    ):
        budget = client.get(path, headers=headers).json()["items"][0]
        assert (budget["usedAttempts"], budget["refundedAttempts"], budget["remainingAttempts"]) == (0, 1, 3)
    assert api.get("/api/v1/qualifiers/status", params={"leagueId": 3023, **MAP}).json()["remainingAttempts"] == 3
    events = admin.get("/admin/api/audit", params={"challengeId": challenge_id}).json()["items"]
    refunds = [e for e in events if e["event"] == "attempt_refunded"]
    assert len(refunds) == 1
    assert refunds[0]["actor"] == "admin:operator"
    assert refunds[0]["details"]["reason"] == "運営判断による再挑戦"
    assert (refunds[0]["details"]["usedBefore"], refunds[0]["details"]["usedAfter"]) == (1, 0)
    feed = api.get("/integration/v1/changes", headers={"Authorization": "Bearer " + token}).json()["items"]
    if receipt is not None:
        current = admin.get(result_path).json()
        assert current == {**original, "attemptRefunded": True, "refundReason": "admin_manual"}
        assert submit(api, data, replay).content == receipt.content
        assert feed[-1]["event"] == "attempt_refunded"
        assert feed[-1]["submission"]["attemptRefunded"] is True
        assert feed[0]["submission"]["attemptRefunded"] is False
        assert len([e for e in feed if e["event"] == "attempt_refunded"]) == 1
    else:
        assert feed == []
    assert verify_database(service.db.path)["challenges"] == 1
    restarted = Service(service.config, service.upstream, service.verifier, clock)
    assert accounting(restarted) == {"used": 0, "total": 1}
    with restarted.db.read() as c:
        row = c.execute("SELECT * FROM challenges WHERE id=?", (challenge_id,)).fetchone()
        assert row["refunded"] == 1 and row["refund_reason"] == "admin_manual"
        assert row["status"] == response.json()["status"]


@pytest.mark.parametrize("expiry", [False, True])
def test_automatic_refund_cannot_be_refunded_again(server, expiry):
    api, admin, service, _, clock, _ = server
    policy(service, refund_conditions=["abandoned", "preflight_unstarted"], challenge_timeout_seconds=5)
    login(api)
    login_admin(admin)
    challenge_id = reserve(api).json()["challengeId"]
    if expiry:
        clock.now += 5
        service.sweep()
    else:
        assert submit(api, metadata(challenge_id)).status_code == 201
    with service.db.read() as c:
        before = [tuple(r) for r in c.execute("SELECT * FROM changes")]
        audits = c.execute("SELECT COUNT(*) FROM audit WHERE event='attempt_refunded'").fetchone()[0]
    response = operate(admin, challenge_id, "refund")
    assert response.status_code == 200
    assert response.json()["refundReason"] == ("abandoned" if expiry else "preflight_unstarted")
    assert accounting(service) == {"used": 0, "total": 1}
    with service.db.read() as c:
        assert [tuple(r) for r in c.execute("SELECT * FROM changes")] == before
        assert c.execute("SELECT COUNT(*) FROM audit WHERE event='attempt_refunded'").fetchone()[0] == audits


@pytest.mark.parametrize("scope", ["sid", "league", "hash", "characteristic", "difficulty"])
def test_refund_is_scoped_to_the_original_budget(server, scope):
    api, admin, service, upstream, _, _ = server
    login(api)
    login_admin(admin)
    challenge_id = reserve(api).json()["challengeId"]
    assert submit(api, metadata(challenge_id)).status_code == 201
    key, league = dict(MAP), 3023
    if scope == "sid":
        login(api, other=True)
    elif scope == "league":
        league = upstream.data["league_id"] = 3024
    else:
        key[scope] = {"hash": "F" * 40, "characteristic": "OneSaber", "difficulty": "Hard"}[scope]
        upstream.data["maps"].append({**upstream.data["maps"][0], **key})
    assert reserve(api, league=league, map_key=key).status_code == 201
    assert operate(admin, challenge_id, "refund").status_code == 200
    with service.db.read() as c:
        rows = c.execute("SELECT used,total FROM budgets ORDER BY used").fetchall()
        assert [tuple(r) for r in rows] == [(0, 1), (1, 1)]
        original = c.execute("SELECT refunded FROM challenges WHERE id=?", (challenge_id,)).fetchone()
        assert original["refunded"] == 1
    assert verify_database(service.db.path)["challenges"] == 2


@pytest.mark.parametrize("action,terminal", [("refund", False), ("force-end", True)])
def test_state_conflict_does_not_change_challenge(server, action, terminal):
    api, admin, service, *_ = server
    login(api)
    login_admin(admin)
    challenge_id = reserve(api).json()["challengeId"]
    if terminal:
        assert submit(api, metadata(challenge_id)).status_code == 201
    response = operate(admin, challenge_id, action)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "challenge_state_conflict"
    assert accounting(service) == {"used": 1, "total": 1}
    assert verify_database(service.db.path)["challenges"] == 1


@pytest.mark.parametrize("action", ["force-end", "refund"])
@pytest.mark.parametrize("reason", [None, "", " \t\n", "x" * 501, True, 10, []])
def test_reason_is_required_and_bounded(server, action, reason):
    api, admin, service, *_ = server
    login(api)
    login_admin(admin)
    challenge_id = reserve(api).json()["challengeId"]
    assert operate(admin, challenge_id, action, reason=reason).status_code == 400
    assert accounting(service) == {"used": 1, "total": 1}


@pytest.mark.parametrize("body", [None, [], {}, {"reason": "理由"}, {"reason": "理由", "refundAttempt": 1},
                                  {"reason": "理由", "refundAttempt": "false"},
                                  {"reason": "理由", "refundAttempt": False, "extra": True}])
def test_force_end_requires_exact_schema(server, body):
    api, admin, _, *_ = server
    login(api)
    login_admin(admin)
    challenge_id = reserve(api).json()["challengeId"]
    response = admin.post(f"/admin/api/challenges/{challenge_id}/force-end", content=json.dumps(body), headers={"Content-Type": "application/json"})
    assert response.status_code == 400


@pytest.mark.parametrize("action", ["force-end", "refund"])
def test_unknown_and_invalid_challenges(server, action):
    _, admin, *_ = server
    login_admin(admin)
    assert operate(admin, str(uuid4()), action).status_code == 404
    assert operate(admin, "not-a-uuid", action).status_code == 400


@pytest.mark.parametrize("action", ["force-end", "refund"])
def test_concurrent_admin_replays_refund_only_once(server, action):
    api, admin, service, *_ = server
    login(api)
    login_admin(admin)
    challenge_id = reserve(api).json()["challengeId"]
    if action == "refund":
        assert submit(api, metadata(challenge_id)).status_code == 201
    with ThreadPoolExecutor(max_workers=16) as pool:
        responses = list(pool.map(lambda _: operate(admin, challenge_id, action, refund=True), range(32)))
    assert all(r.status_code == 200 for r in responses)
    assert len({r.content for r in responses}) == 1
    assert accounting(service) == {"used": 0, "total": 1}
    with service.db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM audit WHERE event='attempt_refunded'").fetchone()[0] == 1
    assert verify_database(service.db.path)["challenges"] == 1


@pytest.mark.parametrize("first", ["result", "force-end"])
def test_force_end_and_result_are_serialized(server, monkeypatch, first):
    api, admin, service, *_ = server
    login(api)
    login_admin(admin)
    challenge_id = reserve(api).json()["challengeId"]
    entered, release = threading.Event(), threading.Event()
    method = "result" if first == "result" else "control_challenge"
    original = getattr(service, method)

    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(service, method, paused)
    actions = {
        "result": lambda: submit(api, metadata(challenge_id)),
        "force-end": lambda: operate(admin, challenge_id, refund=True),
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_task = pool.submit(actions[first])
        try:
            assert entered.wait(10)
            second_task = pool.submit(actions["force-end" if first == "result" else "result"])
        finally:
            release.set()
        assert first_task.result(timeout=15).status_code == (201 if first == "result" else 200)
        assert second_task.result(timeout=15).status_code == 409
    assert accounting(service) == {"used": 1 if first == "result" else 0, "total": 1}
    assert verify_database(service.db.path)["results"] == (1 if first == "result" else 0)


def test_sweep_waiting_on_force_end_cannot_auto_refund(server, monkeypatch):
    api, admin, service, _, clock, _ = server
    policy(service, challenge_timeout_seconds=5, refund_conditions=["abandoned"])
    login(api)
    login_admin(admin)
    challenge_id = reserve(api).json()["challengeId"]
    clock.now += 5
    entered, release = threading.Event(), threading.Event()
    original = service.control_challenge

    def paused(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)

    monkeypatch.setattr(service, "control_challenge", paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(operate, admin, challenge_id)
        try:
            assert entered.wait(10)
            service.sweep()
        finally:
            release.set()
        assert pending.result(timeout=15).status_code == 200
    service.sweep()
    assert accounting(service) == {"used": 1, "total": 1}
    assert operate(admin, challenge_id, "refund").status_code == 200
    assert accounting(service) == {"used": 0, "total": 1}


def test_manual_refund_waits_for_automatic_refund(server, monkeypatch):
    api, admin, service, _, clock, _ = server
    policy(service, challenge_timeout_seconds=5, refund_conditions=["abandoned"])
    login(api)
    login_admin(admin)
    challenge_id = reserve(api).json()["challengeId"]
    clock.now += 5
    entered, release = threading.Event(), threading.Event()
    original = service._apply_refund

    def paused(*args, **kwargs):
        if len(args) == 4:
            entered.set()
            assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "_apply_refund", paused)
    with ThreadPoolExecutor(max_workers=2) as pool:
        sweep = pool.submit(service.sweep)
        try:
            assert entered.wait(10)
            manual = pool.submit(operate, admin, challenge_id, "refund")
        finally:
            release.set()
        sweep.result(timeout=15)
        response = manual.result(timeout=15)
    assert response.status_code == 200
    assert response.json()["refundReason"] == "abandoned"
    assert operate(admin, challenge_id).status_code == 409
    assert accounting(service) == {"used": 0, "total": 1}
    assert verify_database(service.db.path)["challenges"] == 1


@pytest.mark.parametrize("action,refund", [("force-end", False), ("force-end", True), ("refund", False)])
def test_control_state_refund_audit_and_feed_rollback_together(server, monkeypatch, action, refund):
    api, admin, service, *_ = server
    login(api)
    login_admin(admin)
    challenge_id = reserve(api).json()["challengeId"]
    if action == "refund":
        assert submit(api, metadata(challenge_id, "clear"), bsor()).status_code == 201
    with service.db.read() as c:
        before = {table: [tuple(r) for r in c.execute("SELECT * FROM " + table)]
                  for table in ("challenges", "budgets", "results", "replay_blobs", "changes")}
    original = service.db.audit

    def broken_audit(now, actor, event, *args, **kwargs):
        if event == "challenge_force_ended":
            raise sqlite3.OperationalError("simulated failure before commit")
        return original(now, actor, event, *args, **kwargs)

    def broken_change(*args):
        raise sqlite3.OperationalError("simulated failure after refund and audit")

    monkeypatch.setattr(service.db, "audit", broken_audit)
    monkeypatch.setattr(service, "emit_change", broken_change)
    assert operate(admin, challenge_id, action, refund=refund).status_code == 503
    with service.db.read() as c:
        for table, expected in before.items():
            assert [tuple(r) for r in c.execute("SELECT * FROM " + table)] == expected
        assert c.execute("SELECT COUNT(*) FROM audit WHERE event IN ('attempt_refunded','challenge_force_ended')").fetchone()[0] == 0
    monkeypatch.undo()
    assert operate(admin, challenge_id, action, refund=refund).status_code == 200
    assert verify_database(service.db.path)["challenges"] == 1

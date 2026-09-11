import copy
from dataclasses import asdict
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from jbsl_score.api import create_api
from jbsl_score.errors import ApiProblem
from jbsl_score.service import Service, timestamp

from .conftest import MAP, SID, bsor, login, metadata, reserve, submit


def policy(service, **values):
    p, revision = service.db.policy()
    return service.update_policy({**asdict(p), **values}, revision, "test", "test")


@pytest.mark.parametrize(
    "condition,end,reason",
    [
        ("preflight_unstarted", "preflight_rejected", None),
        ("preflight_started", "preflight_rejected", None),
        ("quit", "quit", None),
        ("restart", "restart", None),
        ("unknown", "unknown", None),
        ("submission_disabled", "clear", "submission_disabled"),
        ("replay_unavailable", "fail", "replay_unavailable"),
    ],
)
@pytest.mark.parametrize("enabled", [True, False])
def test_refund_conditions_are_exactly_once(server, condition, end, reason, enabled):
    api, _, service, _, _, _ = server
    policy(service, refund_conditions=[condition] if enabled else [])
    login(api)
    r = reserve(api).json()
    m = metadata(r["challengeId"], end, reason)
    if condition == "preflight_started":
        m["scoreValidity"]["playInstanceCount"] = 1
        m["timing"]["startedAtClient"] = timestamp(service.clock())
    first = submit(api, m)
    assert first.status_code == 201, first.text
    again = submit(api, m)
    assert again.status_code == 200 and first.content == again.content
    assert first.json()["remainingAttempts"] == (3 if enabled else 2)
    with service.db.read() as c:
        assert c.execute("SELECT used FROM budgets").fetchone()[0] == (0 if enabled else 1)
        assert c.execute("SELECT COUNT(*) FROM audit WHERE event='attempt_refunded'").fetchone()[0] == int(enabled)


def test_refund_and_deadline_policy_is_frozen(server):
    api, _, service, _, clock, _ = server
    policy(service, refund_conditions=["preflight_unstarted"], result_grace_seconds=120)
    login(api)
    r = reserve(api).json()
    policy(service, refund_conditions=[], result_grace_seconds=0)
    with service.db.read() as c:
        row = c.execute("SELECT * FROM challenges").fetchone()
    assert row["accept_until"] == row["effective_end"] + 120
    clock.now = row["effective_end"] + 100
    result = submit(api, metadata(r["challengeId"]))
    assert result.status_code == 201 and result.json()["remainingAttempts"] == 3


@pytest.mark.parametrize("offset,expected", [(0, 201), (0.001, 409), (-0.001, 201)])
def test_deadline_boundary(server, offset, expected):
    api, _, service, _, clock, _ = server
    login(api)
    r = reserve(api).json()
    with service.db.read() as c:
        until = c.execute("SELECT accept_until FROM challenges").fetchone()[0]
    clock.now = until + offset
    response = submit(api, metadata(r["challengeId"]))
    assert response.status_code == expected, response.text
    if expected == 409:
        assert response.json()["error"]["code"] == "result_acceptance_expired"


def test_result_deadline_precedes_payload_and_preserves_accepted_result(server):
    api, _, service, _, clock, _ = server
    login(api)
    r = reserve(api).json()
    m = metadata(r["challengeId"], "clear")
    assert submit(api, m, bsor()).status_code == 201
    with service.db.read() as c:
        clock.now = c.execute("SELECT accept_until FROM challenges").fetchone()[0] + 1
    response = api.put(f"/api/v1/qualifiers/challenges/{r['challengeId']}/result", content=b"not a form")
    assert response.status_code == 409 and response.json()["error"]["code"] == "result_acceptance_expired"
    with service.db.read() as c:
        assert c.execute("SELECT status FROM challenges").fetchone()[0] == "submitted"
        assert c.execute("SELECT canceled FROM results").fetchone()[0] == 0


def test_auth_and_ownership_precede_deadline(server):
    api, _, service, _, clock, _ = server
    login(api)
    r = reserve(api).json()
    login(api, other=True)
    clock.now += 5000
    response = submit(api, metadata(r["challengeId"]))
    assert response.status_code == 403
    api.cookies.clear()
    assert submit(api, metadata(r["challengeId"])).status_code == 401


def test_sweep_and_timeout_refund(server):
    api, _, service, _, clock, _ = server
    policy(service, challenge_timeout_seconds=5, refund_conditions=["abandoned"])
    login(api)
    r = reserve(api).json()
    clock.now += 5
    service.sweep()
    service.sweep()
    result = submit(api, metadata(r["challengeId"]))
    assert result.status_code == 409 and result.json()["error"]["code"] == "challenge_timed_out"
    with service.db.read() as c:
        assert c.execute("SELECT used FROM budgets").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM audit WHERE event='attempt_refunded'").fetchone()[0] == 1
    clock.now += 4000
    assert submit(api, metadata(r["challengeId"])).json()["error"]["code"] == "result_acceptance_expired"


def test_submitted_retry_after_operational_timeout(server):
    api, _, service, _, clock, _ = server
    policy(service, challenge_timeout_seconds=5)
    login(api)
    m = metadata(reserve(api).json()["challengeId"])
    first = submit(api, m)
    clock.now += 6
    service.sweep()
    again = submit(api, m)
    assert again.status_code == 200 and again.content == first.content


def test_upload_admission_lock_excludes_sweeper(server):
    api, _, service, _, clock, _ = server
    login(api)
    r = reserve(api).json()
    user = dict(SecurityForTest(service, api))
    lock = service.challenge_lock(r["challengeId"])
    with lock:
        receipt = service.admission(SID, r["challengeId"])
        clock.now += 5000
        service.sweep()
        m = metadata(r["challengeId"])
        status, _ = service.result(user, r["challengeId"], m, None, None, receipt, "test")
        assert status == 201
    service.sweep()
    with service.db.read() as c:
        assert c.execute("SELECT status FROM challenges").fetchone()[0] == "submitted"


def SecurityForTest(service, api):
    from jbsl_score.security import Security

    return Security(service).player(api.cookies.get("jbslq_session"))


def test_reserve_and_result_snapshots_survive_restart(server):
    api, _, service, upstream, clock, _ = server
    login(api)
    key = str(uuid4())
    r = reserve(api, key)
    m = metadata(r.json()["challengeId"])
    response = submit(api, m)
    assert reserve(api).status_code == 201
    upstream.error = ApiProblem(503, "upstream_unavailable", "down")
    restarted = Service(service.config, upstream, service.verifier, clock)
    with TestClient(create_api(restarted, background=False), base_url=service.config.api_public_url) as other:
        other.cookies.update(api.cookies)
        calls = upstream.calls
        again = reserve(other, key)
        assert again.status_code == 200 and again.content == r.content and calls == upstream.calls
        again = submit(other, m)
        assert again.status_code == 200 and again.content == response.content


def test_fresh_cache_does_not_authorize_reserve_and_404_is_not_cached(server):
    api, _, service, upstream, clock, _ = server
    login(api)
    url = "/api/v1/qualifiers/status"
    query = {"leagueId": 3023, **MAP}
    assert api.get(url, params=query).json()["eligible"]
    upstream.error = ApiProblem(503, "upstream_unavailable", "down")
    assert reserve(api).status_code == 503
    assert api.get(url, params=query).json()["cache"]["stale"] is False
    clock.now += 61
    assert api.get(url, params=query).json()["cache"]["stale"] is True
    upstream.error = ApiProblem(502, "upstream_invalid", "bad JSON")
    assert api.get(url, params=query).status_code == 502
    upstream.error = ApiProblem(404, "league_not_found", "missing")
    response = api.get(url, params=query)
    assert response.json()["reasonCode"] == "league_not_found"
    assert response.json()["remainingAttempts"] is None
    assert response.json()["cache"]["fetchedAt"] is not None
    with service.db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM league_cache").fetchone()[0] == 0


@pytest.mark.parametrize(
    "change,expected",
    [
        ("disabled", "qualifier_disabled"),
        ("wrong_method", "wrong_submission_method"),
        ("closed", "league_not_open"),
        ("early", "outside_qualifier_window"),
        ("missing_map", "map_not_found"),
        ("not_participant", "not_participant"),
    ],
)
def test_eligibility_reasons(server, change, expected):
    api, _, _, upstream, clock, _ = server
    p = upstream.data
    if change == "disabled":
        p["qualifier"]["enabled"] = False
    if change == "wrong_method":
        p["qualifier"]["submission_method"] = "other"
    if change == "closed":
        p["isOpen"] = False
    if change == "early":
        p["qualifier"]["starts_at"] = timestamp(clock.now + 100)
    if change == "missing_map":
        p["maps"] = []
    if change == "not_participant":
        p["participants"] = []
    login(api)
    result = api.get("/api/v1/qualifiers/status", params={"leagueId": 3023, **MAP}).json()
    assert not result["eligible"] and result["reasonCode"] == expected
    assert reserve(api).json()["error"]["code"] == expected


def test_duration_deadline_and_missing_duration(server):
    api, _, service, upstream, clock, _ = server
    policy(service, start_deadline_policy="end_minus_duration")
    upstream.data["end"] = timestamp(clock.now + 180)
    login(api)
    assert reserve(api).status_code == 201
    clock.now += 0.001
    assert reserve(api).json()["error"]["code"] == "outside_qualifier_window"
    upstream.data["maps"][0]["song_duration_seconds"] = None
    clock.now -= 300
    assert reserve(api).status_code == 403


def test_map_scope_limits_and_refund_attempt_number(server):
    api, _, service, upstream, _, _ = server
    policy(service, refund_conditions=["preflight_unstarted"])
    other_map = {**MAP, "difficulty": "Hard"}
    upstream.data["maps"].append(
        {**other_map, "title": "Other", "qualifier_attempt_limit": 1, "song_duration_seconds": 120}
    )
    login(api)
    r = reserve(api).json()
    assert submit(api, metadata(r["challengeId"])).status_code == 201
    assert reserve(api).json()["attemptNumber"] == 2
    assert reserve(api, map_key=other_map).json()["remainingAttempts"] == 0
    assert reserve(api, map_key=other_map).status_code == 409
    upstream.data["maps"][0]["qualifier_attempt_limit"] = 1
    assert reserve(api).status_code == 409
    upstream.data["maps"][0]["qualifier_attempt_limit"] = 3
    assert reserve(api).json()["remainingAttempts"] == 1


def test_paused_reservations_allow_recovery(server):
    api, _, service, upstream, _, _ = server
    login(api)
    key = str(uuid4())
    r = reserve(api, key)
    policy(service, reservations_enabled=False)
    upstream.data["participants"] = []
    assert reserve(api).status_code == 403
    assert reserve(api, key).content == r.content
    assert submit(api, metadata(r.json()["challengeId"])).status_code == 201


def test_conflicting_results_and_cross_challenge_key(server):
    api, _, _, _, _, _ = server
    login(api)
    m = metadata(reserve(api).json()["challengeId"])
    assert submit(api, m).status_code == 201
    changed = copy.deepcopy(m)
    changed["energy"] = 0.3
    assert submit(api, changed).json()["error"]["code"] == "result_conflict"
    changed["challengeId"] = reserve(api).json()["challengeId"]
    assert submit(api, changed).json()["error"]["code"] == "idempotency_conflict"

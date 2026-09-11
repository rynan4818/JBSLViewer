import gzip

import httpx
import pytest

from jbsl_score.config import Config
from jbsl_score.contracts import strict_json
from jbsl_score.errors import ApiProblem
from jbsl_score.replay import decode_gzip
from jbsl_score.security import Security
from jbsl_score.upstream import LeaderboardClient, TicketVerifier

from .conftest import MAP, SID, bsor, login, login_admin, metadata, projection, reserve, submit


@pytest.mark.parametrize(
    "path", ["/admin/api/state", "/admin/api/users", "/admin/api/settings", "/admin/api/challenges", "/admin/api/rankings", "/admin/api/audit"]
)
def test_admin_requires_login_and_api_port_is_separate(server, path):
    api, admin, *_ = server
    assert admin.get(path).status_code == 401
    assert api.get(path).status_code == 404


def test_admin_csrf_origin_and_cookie(server):
    api, admin, service, _, _, _ = server
    body = {"username": "operator", "password": "test-admin-password-2026"}
    assert admin.post("/admin/api/login", json=body).status_code == 403
    assert (
        admin.post(
            "/admin/api/login", json=body, headers={"X-JBSL-Admin": "1", "Origin": "https://untrusted.example"}
        ).status_code
        == 403
    )
    response = login_admin(admin)
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/admin" in cookie
    data = admin.get("/admin/api/settings").json()
    assert admin.put("/admin/api/settings", json=data, headers={"X-CSRF-Token": "bad"}).status_code == 403
    assert admin.put("/admin/api/settings", json=data).status_code == 200
    assert admin.put("/admin/api/settings", json=data).status_code == 409
    assert admin.post("/admin/api/logout", json={}).status_code == 204
    assert admin.get("/admin/api/me").status_code == 401


def test_admin_rate_limit_is_persistent(server):
    _, admin, service, _, _, _ = server
    for _ in range(5):
        assert (
            admin.post(
                "/admin/api/login", json={"username": "operator", "password": "wrong"}, headers={"X-JBSL-Admin": "1"}
            ).status_code
            == 401
        )
    assert (
        admin.post(
            "/admin/api/login",
            json={"username": "operator", "password": "test-admin-password-2026"},
            headers={"X-JBSL-Admin": "1"},
        ).status_code
        == 429
    )
    with service.db.read() as c:
        assert c.execute("SELECT count FROM rate_limits WHERE bucket='admin_login'").fetchone()[0] == 6


@pytest.mark.parametrize("action", ["force-end", "refund"])
def test_challenge_controls_require_admin_csrf_and_separate_port(server, action):
    api, admin, service, *_ = server
    login(api)
    challenge_id = reserve(api).json()["challengeId"]
    if action == "refund":
        assert submit(api, metadata(challenge_id)).status_code == 201
    path = f"/admin/api/challenges/{challenge_id}/{action}"
    body = {"reason": "運営操作"}
    if action == "force-end":
        body["refundAttempt"] = True
    assert api.post(path, json=body).status_code == 404
    assert admin.post(path, json=body).status_code == 401
    admin.cookies.set("jbslq_admin", api.cookies.get("jbslq_session"))
    assert admin.post(path, json=body).status_code == 401
    admin.cookies.clear()
    login_admin(admin)
    assert admin.post(path, json=body, headers={"X-CSRF-Token": "bad"}).status_code == 403
    assert admin.post(path, json=body, headers={"Origin": "https://untrusted.example"}).status_code == 403
    with service.db.read() as c:
        assert c.execute("SELECT used FROM budgets").fetchone()[0] == 1
    assert admin.post(path, json=body).status_code == 200


def test_tokens_passwords_and_sessions_are_not_plaintext(server):
    api, admin, service, _, _, token = server
    login(api)
    login_admin(admin)
    with service.db.read() as c:
        raw = " ".join(
            str(tuple(r))
            for table in ("users", "sessions", "admin_users", "admin_sessions", "service_tokens", "audit")
            for r in c.execute("SELECT * FROM " + table)
        )
    for secret in (
        token,
        api.cookies.get("jbslq_session"),
        admin.cookies.get("jbslq_admin"),
        "test-admin-password-2026",
        "mock-ticket",
    ):
        assert secret not in raw
    assert "scrypt$" in raw


def test_cookie_expiration_logout_rotation_and_bearer_revocation(server):
    api, _, service, _, clock, token = server
    first = login(api)
    old_cookie = api.cookies.get("jbslq_session")
    login(api)
    with pytest.raises(ApiProblem):
        Security(service).player(old_cookie)
    assert "HttpOnly" in first.headers["set-cookie"] and "SameSite=lax" in first.headers["set-cookie"]
    assert api.delete("/api/v1/auth/session").status_code == 204
    assert api.get("/api/v1/auth/me").status_code == 401
    login(api)
    clock.now += 43200
    assert api.get("/api/v1/auth/me").status_code == 401
    path = "/integration/v1/changes"
    assert api.get(path).status_code == 401
    assert api.get(path, headers={"Authorization": "Bearer " + token}).status_code == 200
    replacement = Security(service).create_service_token("test-web")
    assert api.get(path, headers={"Authorization": "Bearer " + token}).status_code == 401
    assert api.get(path, headers={"Authorization": "Bearer " + replacement}).status_code == 200


def test_browser_origin_and_dns_rebinding_are_rejected(server):
    api, admin, *_ = server
    assert (
        api.post(
            "/api/v1/auth/session",
            data={"ticket": "mock-ticket", "provider": "steamTicket"},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert admin.get("/admin/", headers={"Host": "evil.example"}).status_code == 400
    assert api.get("/healthz", headers={"Host": "evil.example"}).status_code == 400
    assert admin.get("/admin/").headers["content-security-policy"].find("frame-ancestors 'none'") >= 0


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b"\xff"])
def test_strict_json_rejects_ambiguous_input(raw):
    with pytest.raises((ValueError, UnicodeError)):
        strict_json(raw)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schemaVersion", True),
        ("endType", {}),
        ("energy", float("inf")),
        ("modifiedScore", 2**63),
        ("scoreValidity", []),
        ("map", {"hash": "A" * 40}),
    ],
)
def test_invalid_metadata_never_becomes_500(server, field, value):
    api, _, service, _, _, _ = server
    login(api)
    m = metadata(reserve(api).json()["challengeId"])
    m[field] = value
    response = submit(api, m)
    assert response.status_code in (400, 422), response.text
    with service.db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 0


@pytest.mark.parametrize("payload", [b"bad", b"\x1f\x8b\x08\x00" + b"\0" * 9, gzip.compress(b"bad bsor"), bsor()[:-3]])
def test_invalid_gzip_or_bsor(payload):
    with pytest.raises(ApiProblem) as exc:
        decode_gzip(payload, 16 * 1024 * 1024, 64 * 1024 * 1024)
    assert exc.value.status == 422


def test_gzip_limits():
    with pytest.raises(ApiProblem) as exc:
        decode_gzip(gzip.compress(b"A" * 1000000), 100000, 1000)
    assert exc.value.status == 413
    with pytest.raises(ApiProblem) as exc:
        decode_gzip(bsor(), 1, 1000000)
    assert exc.value.status == 413


@pytest.mark.parametrize("kind", ["sid", "map", "platform", "score", "missing"])
def test_ranked_replay_identity_and_score_checks(server, kind):
    api, _, _, _, _, _ = server
    login(api)
    m = metadata(reserve(api).json()["challengeId"], "clear")
    replay = {
        "sid": lambda: bsor(sid="another"),
        "map": lambda: bsor(key={**MAP, "difficulty": "Hard"}),
        "platform": lambda: bsor(platform="oculus"),
        "score": lambda: bsor(score=114),
        "missing": lambda: None,
    }[kind]()
    response = submit(api, m, replay)
    assert response.status_code == 422, response.text


def test_multiplied_score_not_modified_score_is_bsor_score(server):
    api, _, _, _, _, _ = server
    login(api)
    m = metadata(reserve(api).json()["challengeId"], "clear")
    m["modifiedScore"] = 100
    assert submit(api, m, bsor(score=115)).status_code == 201


@pytest.mark.parametrize("provider", ["steamTicket", "oculusTicket"])
def test_real_provider_http_contract(provider):
    calls = []

    def handler(request):
        calls.append(request)
        if provider == "steamTicket":
            assert request.url.params["appid"] == "620980" and request.url.params["ticket"] == "secret-ticket"
            return httpx.Response(200, json={"response": {"params": {"result": "OK", "steamid": SID}}})
        assert request.headers["Authorization"] == "Bearer secret-ticket"
        return httpx.Response(200, json={"id": SID, "alias": "Player"})

    verifier = TicketVerifier(Config(steam_api_key="secret-key"), httpx.MockTransport(handler))
    assert verifier.verify("secret-ticket", provider).sid == SID
    assert len(calls) == 1


@pytest.mark.parametrize(
    "status,code", [(401, "invalid_ticket"), (500, "auth_provider_unavailable"), (302, "auth_provider_unavailable")]
)
def test_real_provider_failures_do_not_authenticate(status, code):
    verifier = TicketVerifier(
        Config(steam_api_key="key"),
        httpx.MockTransport(lambda _: httpx.Response(status, headers={"Location": "https://evil.example"})),
    )
    with pytest.raises(ApiProblem) as exc:
        verifier.verify("ticket", "steamTicket")
    assert exc.value.code == code


def test_production_has_no_stub_authentication():
    verifier = TicketVerifier(Config())
    with pytest.raises(ApiProblem) as exc:
        verifier.verify("mock-ticket", "steamTicket")
    assert exc.value.code == "auth_provider_unavailable"


@pytest.mark.parametrize("change", ["id", "duplicate_sid", "duplicate_map", "limit", "nan_duration", "missing_field"])
def test_upstream_invalid_schema_and_identity(change):
    data = projection()
    if change == "id":
        data["league_id"] = 123
    if change == "duplicate_sid":
        data["participants"].append(data["participants"][0])
    if change == "duplicate_map":
        data["maps"].append(data["maps"][0])
    if change == "limit":
        data["maps"][0]["qualifier_attempt_limit"] = True
    if change == "nan_duration":
        data["maps"][0]["song_duration_seconds"] = "nan"
    if change == "missing_field":
        del data["isOpen"]
    client = LeaderboardClient(Config(), httpx.MockTransport(lambda _: httpx.Response(200, json=data)))
    with pytest.raises(ApiProblem) as exc:
        client.get(3023)
    assert exc.value.code == "upstream_invalid"


def test_settings_validation(server):
    _, admin, _, _, _, _ = server
    login_admin(admin)
    original = admin.get("/admin/api/settings").json()
    for key, value in [
        ("result_grace_seconds", -1),
        ("refund_conditions", ["clear"]),
        ("reservations_enabled", "true"),
    ]:
        changed = {**original, "policy": {**original["policy"], key: value}}
        assert admin.put("/admin/api/settings", json=changed).status_code == 400
    assert admin.get("/admin/api/settings").json() == original

"""Verify the published contract against real handlers and their responses."""

import json
import re
from dataclasses import asdict
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute
from jsonschema import Draft202012Validator

from jbsl_score.config import Policy
from jbsl_score.documentation import build_openapi
from jbsl_score.openapi_schemas import POLICY_FIELDS
from jbsl_score.service import timestamp

from .conftest import MAP, NOW, SID, bsor, login, login_admin, metadata, reserve, submit


def check_response(document, path, method, response, expected=200):
    assert response.status_code == expected, response.text
    operation = document["paths"][path][method]
    schema = operation["responses"][str(expected)]["content"]["application/json"]["schema"]
    Draft202012Validator({**schema, "components": document["components"]}).validate(response.json())


def test_documentation_is_public_but_data_and_api_port_are_protected(server):
    api, admin, service, _, _, token = server
    for path in ("/admin/docs/", "/admin/guide/", "/admin/openapi.json"):
        response = admin.get(path)
        assert response.status_code == 200
        assert "no-store" in response.headers["cache-control"]
        assert "'unsafe-inline'" not in response.headers["content-security-policy"]
        assert ("img-src 'self' data:" in response.headers["content-security-policy"]) == (path == "/admin/docs/")
        assert "Set-Cookie" not in response.headers
        assert api.get(path).status_code == 404
    assert admin.get("/admin/api/state").status_code == 401
    assert admin.get("/admin/api/settings").status_code == 401
    assert "data:" not in admin.get("/admin/").headers["content-security-policy"]
    assert api.get("/api/v1/auth/me", headers={"Origin": service.config.admin_public_url}).status_code == 403
    doc = admin.get("/admin/openapi.json").json()
    assert token not in json.dumps(doc)
    service.config.steam_api_key = "secret-steam-key-never-publish"
    service.config.jbsl_web_token = "secret-upstream-token-never-publish"
    published = json.dumps(build_openapi(service.config))
    assert service.config.steam_api_key not in published
    assert service.config.jbsl_web_token not in published


def test_public_rankings_contract_and_security(server):
    api, admin, *_ = server
    doc = admin.get("/admin/openapi.json").json()
    path = "/admin/api/public/rankings"
    assert doc["paths"][path]["get"]["security"] == []
    assert doc["paths"]["/admin/api/rankings"]["get"]["security"] == [{"AdminSession": []}]
    check_response(doc, path, "get", admin.get(path))
    login(api)
    submit(api, metadata(reserve(api).json()["challengeId"], end="clear"), bsor())
    check_response(doc, path, "get", admin.get(path))
    check_response(doc, path, "get", admin.get(path, params={"leagueId": "bad"}), 400)
    check_response(doc, path, "get", admin.get(path, params={"leagueId": 9999}), 404)
    assert not admin.cookies


def test_all_actual_api_operations_have_complete_documentation(server):
    api, admin, service, *_ = server
    doc = admin.get("/admin/openapi.json").json()
    actual = {
        (route.path, method.lower())
        for app in (api.app, admin.app)
        for route in app.routes
        if isinstance(route, APIRoute)
        and (route.path.startswith(("/api/", "/integration/", "/admin/api/")) or route.path in ("/healthz", "/readyz"))
        for method in route.methods
    }
    declared = {(path, method) for path, methods in doc["paths"].items() for method in methods}
    assert actual == declared
    ids = []
    for path, method in declared:
        op = doc["paths"][path][method]
        ids.append(op["operationId"])
        assert op["summary"] and op["tags"]
        expected_origin = (
            service.config.admin_public_url if path.startswith("/admin/") else service.config.api_public_url
        )
        assert op.get("servers", doc["servers"])[0]["url"] == expected_origin
        path_params = {p["name"] for p in op.get("parameters", []) if p["in"] == "path" and p["required"]}
        assert path_params == set(re.findall(r"\{([^}]+)\}", path))
        for response in op["responses"].values():
            assert response["description"]
    assert len(ids) == len(set(ids))
    for schema in doc["components"]["schemas"].values():
        Draft202012Validator.check_schema(schema)
    # Every local $ref resolves; a typo would otherwise leave a broken model in Swagger.
    for ref_path in re.findall(r'"\$ref": "([^"]+)"', json.dumps(doc)):
        target = doc
        for segment in ref_path.removeprefix("#/").split("/"):
            target = target[segment]


def test_viewer_flow_and_integration_responses_match_openapi(server):
    api, admin, _, _, _, token = server
    doc = admin.get("/admin/openapi.json").json()
    check_response(doc, "/api/v1/auth/session", "post", login(api))
    check_response(doc, "/api/v1/auth/me", "get", api.get("/api/v1/auth/me"))
    check_response(
        doc, "/api/v1/qualifiers/status", "get", api.get("/api/v1/qualifiers/status", params={"leagueId": 3023, **MAP})
    )
    reservation = reserve(api)
    check_response(doc, "/api/v1/qualifiers/challenges", "post", reservation, 201)
    challenge_id = reservation.json()["challengeId"]
    started = {
        "schemaVersion": 1,
        "actualMap": MAP,
        "gameMode": "Solo",
        "practice": False,
        "submissionAllowed": True,
        "startedAtClient": timestamp(NOW),
    }
    check_response(
        doc,
        "/api/v1/qualifiers/challenges/{challenge_id}/started",
        "post",
        api.post(f"/api/v1/qualifiers/challenges/{challenge_id}/started", json=started),
    )
    data = metadata(challenge_id, end="clear")
    Draft202012Validator({"$ref": "#/components/schemas/ResultMetadata", "components": doc["components"]}).validate(
        data
    )
    receipt = submit(api, data, bsor())
    check_response(doc, "/api/v1/qualifiers/challenges/{challenge_id}/result", "put", receipt, 201)
    check_response(doc, "/api/v1/qualifiers/challenges/{challenge_id}/result", "put", submit(api, data, bsor()))
    submission_id = receipt.json()["submissionId"]
    headers = {"Authorization": "Bearer " + token}
    for template, path in (
        ("/integration/v1/changes", "/integration/v1/changes"),
        ("/integration/v1/submissions/{submission_id}", f"/integration/v1/submissions/{submission_id}"),
        ("/integration/v1/leagues/{league_id}/leaderboard", "/integration/v1/leagues/3023/leaderboard"),
        (
            "/integration/v1/leagues/{league_id}/users/{sid}/attempts",
            f"/integration/v1/leagues/3023/users/{SID}/attempts",
        ),
    ):
        check_response(doc, template, "get", api.get(path, headers=headers))
    for path in ("/healthz", "/readyz"):
        check_response(doc, path, "get", api.get(path))


def test_challenge_controls_and_refund_feed_match_openapi(server):
    api, admin, _, _, _, token = server
    doc = admin.get("/admin/openapi.json").json()
    login(api)
    login_admin(admin)
    challenge_id = reserve(api).json()["challengeId"]
    force_path = "/admin/api/challenges/{challenge_id}/force-end"
    refund_path = "/admin/api/challenges/{challenge_id}/refund"
    check_response(doc, refund_path, "post", admin.post(refund_path.format(challenge_id=challenge_id), json={"reason": "進行中"}), 409)
    check_response(doc, force_path, "post", admin.post(force_path.format(challenge_id=challenge_id), json={"reason": "強制終了", "refundAttempt": False}))
    check_response(doc, refund_path, "post", admin.post(refund_path.format(challenge_id=challenge_id), json={"reason": "手動返却"}))
    check_response(doc, "/admin/api/challenges", "get", admin.get("/admin/api/challenges"))
    challenge_id = reserve(api).json()["challengeId"]
    result = submit(api, metadata(challenge_id, "clear"), bsor()).json()
    check_response(doc, refund_path, "post", admin.post(refund_path.format(challenge_id=challenge_id), json={"reason": "手動返却"}))
    check_response(doc, "/admin/api/submissions/{submission_id}", "get", admin.get(f"/admin/api/submissions/{result['submissionId']}"))
    feed = api.get("/integration/v1/changes", headers={"Authorization": "Bearer " + token})
    check_response(doc, "/integration/v1/changes", "get", feed)
    assert feed.json()["items"][-1]["event"] == "attempt_refunded"
    for path in (force_path, refund_path):
        operation = doc["paths"][path]["post"]
        assert operation["security"] == [{"AdminSession": [], "AdminCsrf": []}]


def test_admin_operations_match_openapi_and_keep_security(server):
    api, admin, *_ = server
    doc = admin.get("/admin/openapi.json").json()
    login(api)
    result = submit(api, metadata(reserve(api).json()["challengeId"], end="clear"), bsor()).json()
    submission_id = result["submissionId"]
    check_response(doc, "/admin/api/login", "post", login_admin(admin))
    for path in ("me", "state", "settings", "challenges", "rankings", "users", "audit"):
        check_response(doc, "/admin/api/" + path, "get", admin.get("/admin/api/" + path))
    check_response(doc, "/admin/api/users/{sid}/attempts", "get", admin.get(f"/admin/api/users/{SID}/attempts"))
    check_response(
        doc, "/admin/api/submissions/{submission_id}", "get", admin.get(f"/admin/api/submissions/{submission_id}")
    )
    settings = admin.get("/admin/api/settings").json()
    settings["policy"]["result_grace_seconds"] = 420
    check_response(doc, "/admin/api/settings", "put", admin.put("/admin/api/settings", json=settings))
    check_response(doc, "/admin/api/settings", "put", admin.put("/admin/api/settings", json=settings), 409)
    for version, action in enumerate(("cancel", "restore")):
        check_response(
            doc,
            "/admin/api/submissions/{submission_id}/moderate",
            "post",
            admin.post(
                f"/admin/api/submissions/{submission_id}/moderate",
                json={"version": version, "action": action, "reason": "contract validation"},
            ),
        )
    check_response(doc, "/admin/api/backups", "post", admin.post("/admin/api/backups"))
    check_response(doc, "/admin/api/leagues/{league_id}/refresh", "post", admin.post("/admin/api/leagues/3023/refresh"))
    for methods in doc["paths"].values():
        for op in methods.values():
            if "管理・変更" in op["tags"]:
                assert op["security"] == [{"AdminSession": [], "AdminCsrf": []}]


@pytest.mark.parametrize("field", POLICY_FIELDS)
def test_documented_policy_bounds_match_runtime(field):
    low, high, _ = POLICY_FIELDS[field]
    for value, allowed in ((low, True), (high, True), (low - 1, False), (high + 1, False)):
        raw = asdict(Policy())
        # Maintain the independent fresh <= stale constraint for its boundary cases.
        if field == "cache_stale_seconds":
            raw["cache_fresh_seconds"] = 0
        raw[field] = value
        if allowed:
            assert getattr(Policy.parse(raw), field) == value
        else:
            with pytest.raises(ValueError):
                Policy.parse(raw)


def test_documented_metadata_required_fields_and_multipart_contract(server):
    from jbsl_score.metadata import REQUIRED_RESULT_KEYS

    doc = server[1].get("/admin/openapi.json").json()
    assert set(doc["components"]["schemas"]["ResultMetadata"]["required"]) == REQUIRED_RESULT_KEYS
    policy = doc["components"]["schemas"]["Policy"]
    assert {key: value["default"] for key, value in policy["properties"].items()} == asdict(Policy())
    op = doc["paths"]["/api/v1/qualifiers/challenges/{challenge_id}/result"]["put"]
    body = op["requestBody"]["content"]["multipart/form-data"]
    assert body["schema"]["required"] == ["metadata"]
    assert body["encoding"]["metadata"]["contentType"] == "application/json"
    assert body["encoding"]["replay"]["contentType"] == "application/gzip"
    assert {"200", "201", "409", "413", "422"} <= set(op["responses"])
    for end in ("clear", "fail", "quit", "restart", "unknown", "preflight_rejected"):
        Draft202012Validator({"$ref": "#/components/schemas/ResultMetadata", "components": doc["components"]}).validate(
            metadata(str(uuid4()), end=end)
        )

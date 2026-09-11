from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from starlette.datastructures import UploadFile

from . import replay_viewer, reports
from .contracts import normalize_map, require_positive_int, require_uuid, strict_json
from .errors import ApiProblem
from .http import Guard, install_errors, json_body
from .metadata import validate_metadata
from .replay import decode_gzip, decompress_gzip
from .security import Security
from .service import timestamp


def create_api(service, *, background=True):
    @asynccontextmanager
    async def lifespan(app):
        from .maintenance import start_maintenance

        async with start_maintenance(service, enabled=background):
            yield

    app = FastAPI(
        title="JBSL Score API", version="1.0.0", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    app.state.service = service
    app.add_middleware(Guard, service=service, kind="api")
    install_errors(app, service)
    security = Security(service)
    secure_cookie = service.config.api_public_url.startswith("https://")

    async def player(request, bucket):
        user = await run_in_threadpool(security.player, request.cookies.get("jbslq_session"))
        request.state.actor = user["sid"]
        policy, _ = await run_in_threadpool(service.db.policy)
        limit = {
            "status": policy.status_per_minute,
            "reserve": policy.reserve_per_minute,
            "result": policy.result_per_minute,
            "started": policy.result_per_minute,
            "me": policy.status_per_minute,
        }[bucket]
        await run_in_threadpool(service.db.rate_limit, bucket, user["sid"], limit, service.clock())
        return user

    async def integration(request):
        name = await run_in_threadpool(security.service_token, request.headers.get("authorization"))
        request.state.actor = "service:" + name
        await run_in_threadpool(service.db.rate_limit, "integration", name, 600, service.clock())

    async def authorize_replay(request, submission_id, player_id):
        await run_in_threadpool(service.db.rate_limit, "replay_viewer_ip", request.client.host, 120, service.clock())
        tokens = request.query_params.getlist("token")
        token = tokens[0] if len(tokens) == 1 else None
        user = await run_in_threadpool(
            replay_viewer.authorize, service, submission_id, player_id, token, request.headers.get("origin"),
        )
        request.state.actor = "admin:" + user["username"]
        request.state.replay_viewer_origin = request.headers.get("origin")
        return token

    @app.get(replay_viewer.REPLAY_PATH)
    async def view_replay(submission_id: str, player_id: str, request: Request):
        submission_id = require_uuid(submission_id, "submissionId")
        token = await authorize_replay(request, submission_id, player_id)
        data = await run_in_threadpool(replay_viewer.read_replay, service, submission_id, token)
        return Response(data, media_type="application/octet-stream")

    @app.options(replay_viewer.REPLAY_PATH)
    async def replay_preflight(submission_id: str, player_id: str, request: Request):
        if (
            request.headers.get("origin") not in replay_viewer.VIEWER_ORIGINS
            or request.headers.get("access-control-request-method") != "GET"
            or request.headers.get("access-control-request-headers", "").strip()
        ):
            raise ApiProblem(403, "replay_viewer_origin_rejected", "This replay preflight is not permitted.")
        await authorize_replay(request, submission_id, player_id)
        return Response(status_code=204, headers={"Access-Control-Allow-Methods": "GET"})

    async def read_public_replay(request, submission_id, player_id, *, metadata_only=False):
        await run_in_threadpool(service.db.rate_limit, "public_replay_ip", request.client.host, 120, service.clock())
        data = await run_in_threadpool(
            reports.public_replay, service, submission_id, player_id, metadata_only=metadata_only,
        )
        request.state.replay_viewer_origin = request.headers.get("origin")
        return data

    @app.get(replay_viewer.PUBLIC_REPLAY_PATH)
    async def public_view_replay(submission_id: str, player_id: str, request: Request):
        compressed = await read_public_replay(request, submission_id, player_id)
        data = await run_in_threadpool(
            decompress_gzip, compressed, service.config.compressed_replay_limit, service.config.expanded_replay_limit,
        )
        return Response(data, media_type="application/octet-stream")

    @app.options(replay_viewer.PUBLIC_REPLAY_PATH)
    async def public_replay_preflight(submission_id: str, player_id: str, request: Request):
        if (
            request.headers.get("origin") not in replay_viewer.VIEWER_ORIGINS
            or request.headers.get("access-control-request-method") != "GET"
            or request.headers.get("access-control-request-headers", "").strip()
        ):
            raise ApiProblem(403, "replay_viewer_origin_rejected", "This replay preflight is not permitted.")
        await read_public_replay(request, submission_id, player_id, metadata_only=True)
        return Response(status_code=204, headers={"Access-Control-Allow-Methods": "GET"})

    @app.post("/api/v1/auth/session")
    async def auth(request: Request):
        policy, _ = await run_in_threadpool(service.db.policy)
        await run_in_threadpool(
            service.db.rate_limit, "auth", request.client.host, policy.auth_per_minute, service.clock()
        )
        if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
            raise ApiProblem(400, "malformed_request", "Authentication requires an URL-encoded form.")
        async with request.form(max_files=0, max_fields=3, max_part_size=16384) as form:
            if (
                len(form.multi_items()) != len(form)
                or set(form) - {"ticket", "provider", "returnUrl"}
                or form.get("returnUrl", "/") != "/"
            ):
                raise ApiProblem(400, "malformed_request", "Authentication form is invalid.")
            token, body = await run_in_threadpool(
                security.login_player, form.get("ticket"), form.get("provider"), request.cookies.get("jbslq_session")
            )
        response = JSONResponse(body)
        response.set_cookie(
            "jbslq_session",
            token,
            path="/",
            httponly=True,
            secure=secure_cookie,
            samesite="lax",
            max_age=policy.session_seconds,
        )
        return response

    @app.get("/api/v1/auth/me")
    async def me(request: Request):
        user = await player(request, "me")
        return {
            "schemaVersion": 1,
            "authenticated": True,
            "user": {"sid": user["sid"], "displayName": user["display_name"]},
            "expiresAt": timestamp(user["expires_at"]),
        }

    @app.delete("/api/v1/auth/session")
    async def logout(request: Request):
        user = await player(request, "me")

        def revoke():
            with service.db.transaction() as c:
                c.execute("DELETE FROM sessions WHERE token_hash=?", (user["token_hash"],))

        await run_in_threadpool(revoke)
        response = Response(status_code=204)
        response.delete_cookie("jbslq_session", path="/", httponly=True, secure=secure_cookie, samesite="lax")
        return response

    @app.get("/api/v1/qualifiers/status")
    async def status(request: Request):
        user = await player(request, "status")
        league_id = require_positive_int(reports.integer_query(request.query_params, "leagueId"), "leagueId")
        key = normalize_map({k: request.query_params.get(k) for k in ("hash", "characteristic", "difficulty")})
        return await run_in_threadpool(service.status, user["sid"], league_id, key)

    @app.post("/api/v1/qualifiers/challenges")
    async def reserve(request: Request):
        user = await player(request, "reserve")
        key = require_uuid(request.headers.get("idempotency-key"), "Idempotency-Key")
        body = await json_body(request)
        status, response = await run_in_threadpool(service.reserve, user, key, body, request.state.request_id)
        return Response(response, status_code=status, media_type="application/json")

    @app.post("/api/v1/qualifiers/challenges/{challenge_id}/started")
    async def started(challenge_id: str, request: Request):
        user = await player(request, "started")
        challenge_id = require_uuid(challenge_id, "challengeId")
        request.state.challenge_id = challenge_id
        return await run_in_threadpool(
            service.started, user, challenge_id, await json_body(request), request.state.request_id
        )

    @app.put("/api/v1/qualifiers/challenges/{challenge_id}/result")
    async def result(challenge_id: str, request: Request):
        user = await player(request, "result")
        challenge_id = require_uuid(challenge_id, "challengeId")
        request.state.challenge_id = challenge_id
        lock = service.challenge_lock(challenge_id)
        await run_in_threadpool(service.owned_challenge, user["sid"], challenge_id)
        await lock.acquire_async()
        try:
            received = await run_in_threadpool(service.admission, user["sid"], challenge_id)
            key = require_uuid(request.headers.get("idempotency-key"), "Idempotency-Key")
            if not request.headers.get("content-type", "").lower().startswith("multipart/form-data;"):
                raise ApiProblem(400, "malformed_request", "Result must be multipart/form-data.")
            config = service.config
            length = request.headers.get("content-length")
            if length and int(length) > config.compressed_replay_limit + config.metadata_limit + 16384:
                raise ApiProblem(413, "replay_too_large", "Multipart body exceeds the configured limit.")
            async with request.form(max_files=2, max_fields=1, max_part_size=config.metadata_limit) as form:
                parts = form.multi_items()
                if (
                    sum(n == "metadata" for n, _ in parts) != 1
                    or sum(n == "replay" for n, _ in parts) > 1
                    or any(n not in ("metadata", "replay") for n, _ in parts)
                ):
                    raise ApiProblem(400, "malformed_request", "Multipart parts are invalid.")
                part = form["metadata"]
                raw = (
                    await part.read(config.metadata_limit + 1) if isinstance(part, UploadFile) else part.encode("utf-8")
                )
                if len(raw) > config.metadata_limit:
                    raise ApiProblem(413, "malformed_request", "Result metadata is too large.")
                try:
                    metadata = validate_metadata(strict_json(raw), challenge_id, key)
                except (ValueError, UnicodeDecodeError, RecursionError):
                    raise ApiProblem(400, "malformed_request", "Metadata must be valid UTF-8 JSON.") from None
                part = form.get("replay")
                compressed, replay = None, None
                if part is not None:
                    if not isinstance(part, UploadFile):
                        raise ApiProblem(400, "malformed_request", "Replay must be a file part.")
                    compressed = await part.read(config.compressed_replay_limit + 1)
                    replay = await run_in_threadpool(
                        decode_gzip, compressed, config.compressed_replay_limit, config.expanded_replay_limit
                    )
                status, response = await run_in_threadpool(
                    service.result, user, challenge_id, metadata, replay, compressed, received, request.state.request_id
                )
            return Response(response, status_code=status, media_type="application/json")
        finally:
            lock.release()

    @app.get("/healthz")
    async def health():
        return {"status": "ok", "service": "jbsl-score", "version": "1.0.0"}

    @app.get("/readyz")
    async def ready():
        def check():
            policy, _ = service.db.policy()
            service.check_disk(policy)
            with service.db.read() as c:
                c.execute("SELECT 1").fetchone()
            return {"status": "ok", "database": "ok"}

        return await run_in_threadpool(check)

    @app.get("/integration/v1/changes")
    async def changes(request: Request):
        await integration(request)
        return await run_in_threadpool(reports.changes, service, request.query_params)

    @app.get("/integration/v1/submissions/{submission_id}")
    async def submission(submission_id: str, request: Request):
        await integration(request)
        submission_id = require_uuid(submission_id, "submissionId")

        def get():
            with service.db.read() as c:
                return {"schemaVersion": 1, **service.export_result(c, submission_id)}

        return await run_in_threadpool(get)

    @app.get("/integration/v1/leagues/{league_id}/leaderboard")
    async def board(league_id: str, request: Request):
        await integration(request)
        parsed = require_positive_int(reports.integer_query({"leagueId": league_id}, "leagueId"), "leagueId")
        return await run_in_threadpool(reports.leaderboard, service, parsed)

    @app.get("/integration/v1/leagues/{league_id}/users/{sid}/attempts")
    async def attempts(league_id: str, sid: str, request: Request):
        await integration(request)
        parsed = require_positive_int(reports.integer_query({"leagueId": league_id}, "leagueId"), "leagueId")
        response = await run_in_threadpool(reports.user_budgets, service, sid)
        response["items"] = [x for x in response["items"] if x["leagueId"] == parsed]
        return {"schemaVersion": 1, **response}

    return app

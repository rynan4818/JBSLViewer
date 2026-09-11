import json
from dataclasses import asdict

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import replay_viewer, reports
from .config import ROOT
from .contracts import require_positive_int, require_uuid
from .documentation import build_openapi
from .errors import ApiProblem
from .http import Guard, install_errors, json_body
from .maintenance import backup
from .security import Security
from .service import timestamp


def create_admin(service):
    app = FastAPI(title="JBSL Score Administration", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.service = service
    app.add_middleware(Guard, service=service, kind="admin")
    install_errors(app, service)
    security = Security(service)
    secure_cookie = service.config.admin_public_url.startswith("https://")
    assets = ROOT / "jbsl_score" / "static"
    app.mount("/admin/static", StaticFiles(directory=assets), name="static")
    # Only configuration origins enter this document; it never reads users, tokens or scores.
    schema = build_openapi(service.config)
    app.openapi = lambda: schema

    @app.get("/admin/docs/", include_in_schema=False)
    async def api_documentation():
        return FileResponse(assets / "swagger.html", media_type="text/html")

    @app.get("/admin/openapi.json", include_in_schema=False)
    async def api_schema():
        return JSONResponse(schema)

    @app.get("/admin/guide/", include_in_schema=False)
    async def operator_guide():
        return FileResponse(assets / "guide.html", media_type="text/html")

    async def admin(request, mutation=False):
        user = await run_in_threadpool(
            security.admin, request.cookies.get("jbslq_admin"), request.headers.get("x-csrf-token"), mutation
        )
        request.state.actor = "admin:" + user["username"]
        await run_in_threadpool(service.db.rate_limit, "admin", user["username"], 600, service.clock())
        return user

    @app.get("/")
    async def root():
        return RedirectResponse("/admin/", status_code=302)

    @app.get("/admin/")
    async def page():
        return FileResponse(assets / "index.html", media_type="text/html")

    @app.get("/admin/rankings/", include_in_schema=False)
    async def public_rankings_page():
        return FileResponse(assets / "rankings.html", media_type="text/html")

    @app.get("/admin/api/public/rankings")
    async def public_rankings(request: Request):
        return await run_in_threadpool(reports.public_rankings, service, request.query_params)

    @app.get(replay_viewer.PUBLIC_DOWNLOAD_PATH)
    async def public_replay(submission_id: str, request: Request):
        await run_in_threadpool(service.db.rate_limit, "public_replay_ip", request.client.host, 120, service.clock())
        submission_id = require_uuid(submission_id, "submissionId")
        data = await run_in_threadpool(reports.public_replay, service, submission_id)
        return Response(
            data, media_type="application/gzip",
            headers={"Content-Disposition": f'attachment; filename="{submission_id}.bsor.gz"'},
        )

    @app.post("/admin/api/login")
    async def login(request: Request):
        # Custom header + JSON require a CORS preflight for other browser origins; no CORS is enabled.
        if request.headers.get("x-jbsl-admin") != "1":
            raise ApiProblem(403, "csrf_rejected", "この管理画面からログインしてください。")
        await run_in_threadpool(service.db.rate_limit, "admin_login", request.client.host, 5, service.clock())
        body = await json_body(request)
        if not isinstance(body, dict) or set(body) != {"username", "password"}:
            raise ApiProblem(400, "malformed_request", "Login schema is invalid.")
        token, result = await run_in_threadpool(
            security.login_admin, body["username"], body["password"], request.cookies.get("jbslq_admin")
        )
        response = JSONResponse(result)
        response.set_cookie(
            "jbslq_admin", token, path="/admin", httponly=True, secure=secure_cookie, samesite="strict", max_age=28800
        )
        return response

    @app.get("/admin/api/me")
    async def me(request: Request):
        user = await admin(request)
        return {
            "username": user["username"],
            "csrfToken": user["csrf_token"],
            "expiresAt": timestamp(user["expires_at"]),
        }

    @app.post("/admin/api/logout")
    async def logout(request: Request):
        user = await admin(request, True)

        def revoke():
            with service.db.transaction() as c:
                c.execute("DELETE FROM admin_sessions WHERE token_hash=?", (user["token_hash"],))

        await run_in_threadpool(revoke)
        response = Response(status_code=204)
        response.delete_cookie("jbslq_admin", path="/admin", httponly=True, secure=secure_cookie, samesite="strict")
        return response

    @app.get("/admin/api/state")
    async def state(request: Request):
        await admin(request)
        return await run_in_threadpool(reports.dashboard, service)

    @app.get("/admin/api/settings")
    async def settings(request: Request):
        await admin(request)
        policy, revision = await run_in_threadpool(service.db.policy)
        return {"revision": revision, "policy": asdict(policy)}

    @app.put("/admin/api/settings")
    async def update_settings(request: Request):
        await admin(request, True)
        body = await json_body(request)
        if not isinstance(body, dict) or set(body) != {"policy", "revision"}:
            raise ApiProblem(400, "malformed_request", "設定の形式が不正です。")
        return await run_in_threadpool(
            service.update_policy, body["policy"], body["revision"], request.state.actor, request.state.request_id
        )

    @app.get("/admin/api/challenges")
    async def challenges(request: Request):
        await admin(request)
        return await run_in_threadpool(reports.challenges, service, request.query_params)

    @app.get("/admin/api/rankings")
    async def rankings(request: Request):
        await admin(request)
        return await run_in_threadpool(reports.rankings, service, request.query_params)

    async def control_challenge(challenge_id, request, action):
        await admin(request, True)
        challenge_id = require_uuid(challenge_id, "challengeId")
        request.state.challenge_id = challenge_id
        body = await json_body(request)
        lock = service.challenge_lock(challenge_id)
        await lock.acquire_async()
        try:
            return await run_in_threadpool(
                service.control_challenge, challenge_id, action, body, request.state.actor, request.state.request_id
            )
        finally:
            lock.release()

    @app.post("/admin/api/challenges/{challenge_id}/force-end")
    async def force_end(challenge_id: str, request: Request):
        return await control_challenge(challenge_id, request, "force-end")

    @app.post("/admin/api/challenges/{challenge_id}/refund")
    async def refund(challenge_id: str, request: Request):
        return await control_challenge(challenge_id, request, "refund")

    @app.get("/admin/api/users")
    async def users(request: Request):
        await admin(request)
        return await run_in_threadpool(reports.users, service, request.query_params)

    @app.get("/admin/api/users/{sid}/attempts")
    async def attempts(sid: str, request: Request):
        await admin(request)
        return await run_in_threadpool(reports.user_budgets, service, sid)

    @app.get("/admin/api/audit")
    async def audit(request: Request):
        await admin(request)
        return await run_in_threadpool(reports.audit, service, request.query_params)

    @app.get("/admin/api/submissions/{submission_id}")
    async def submission(submission_id: str, request: Request):
        await admin(request)
        submission_id = require_uuid(submission_id, "submissionId")

        def get():
            with service.db.read() as c:
                result = service.export_result(c, submission_id)
                row = c.execute("SELECT metadata_json FROM results WHERE id=?", (submission_id,)).fetchone()
                challenge = c.execute(
                    "SELECT policy_json,policy_revision FROM challenges WHERE id=?", (result["challengeId"],)
                ).fetchone()
            return {
                **result,
                "metadata": json.loads(row["metadata_json"]),
                "reservationPolicy": json.loads(challenge["policy_json"]),
                "policyRevision": challenge["policy_revision"],
                "replayViewerAvailable": replay_viewer.available(service),
            }

        return await run_in_threadpool(get)

    @app.post("/admin/api/submissions/{submission_id}/moderate")
    async def moderate(submission_id: str, request: Request):
        await admin(request, True)
        submission_id = require_uuid(submission_id, "submissionId")
        body = await json_body(request)
        if not isinstance(body, dict) or set(body) != {"action", "version", "reason"}:
            raise ApiProblem(400, "malformed_request", "取消・復元の形式が不正です。")
        return await run_in_threadpool(
            service.moderate,
            submission_id,
            body["action"],
            body["version"],
            body["reason"],
            request.state.actor,
            request.state.request_id,
        )

    @app.post("/admin/api/submissions/{submission_id}/replay-viewer")
    async def replay_viewer_link(submission_id: str, request: Request):
        user = await admin(request, True)
        body = await json_body(request)
        return await run_in_threadpool(replay_viewer.issue, service, user, submission_id, body, request.state.request_id)

    @app.get("/admin/api/submissions/{submission_id}/replay")
    async def replay(submission_id: str, request: Request):
        await admin(request)
        submission_id = require_uuid(submission_id, "submissionId")

        def get():
            with service.db.read() as c:
                row = c.execute("SELECT gzip_data FROM replay_blobs WHERE result_id=?", (submission_id,)).fetchone()
            if row is None:
                raise ApiProblem(404, "replay_not_found", "Replay does not exist.")
            return row[0]

        data = await run_in_threadpool(get)
        return Response(
            data,
            media_type="application/gzip",
            headers={"Content-Disposition": f'attachment; filename="{submission_id}.bsor.gz"'},
        )

    @app.post("/admin/api/backups")
    async def create_backup(request: Request):
        await admin(request, True)
        return await run_in_threadpool(backup, service, request.state.actor)

    @app.post("/admin/api/leagues/{league_id}/refresh")
    async def refresh(league_id: str, request: Request):
        await admin(request, True)
        league_id = require_positive_int(reports.integer_query({"leagueId": league_id}, "leagueId"), "leagueId")
        projection, fetched_at = await run_in_threadpool(service.fetch_projection, league_id)
        return {
            "leagueId": league_id,
            "revision": projection["qualifier"]["revision"],
            "fetchedAt": timestamp(fetched_at),
        }

    return app

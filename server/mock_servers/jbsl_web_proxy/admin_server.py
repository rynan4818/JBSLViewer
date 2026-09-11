"""Administration listener for loopback or a configured Tunnel origin."""
from __future__ import annotations

import copy
import json

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
import httpx

from .admin_auth import COOKIE_NAME, SESSION_SECONDS
from .config import ROOT, prepare_http_scope, utc_now
from .control import Behavior, Control
from .errors import ApiProblem, problem_response
from .jbsl_web_proxy_server import ranking_sids
from .public_qualifiers import PUBLIC_API, create_router as public_qualifier_router
from .schemas import utc_text


def make_apps(control: Control):
    from .jbsl_web_proxy_server import create_app as proxy_app
    control.proxy_app = proxy_app(control.base_settings, control=control)
    return create_app(control), control.proxy_app


def create_app(control: Control):
    app = FastAPI(title="JBSL-WEB Relay Control", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.control = control

    @app.exception_handler(ApiProblem)
    async def problem(_, exc):
        return problem_response(exc)

    @app.middleware("http")
    async def allowed_origin(request: Request, call_next):
        try:
            if not prepare_http_scope(request.scope, control.base_settings.public_url):
                raise ApiProblem(403, "local_only", "このホストからの管理画面への接続は許可されていません。")
            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
                raise ApiProblem(403, "cross_origin", "別サイトからの管理操作は許可されません。")
            mutation = request.method not in {"GET", "HEAD"}
            path = request.scope["path"]
            login = path == "/admin/api/login" and request.method == "POST"
            if (path == "/admin/api" or path.startswith("/admin/api/")) and not login:
                request.state.admin = await run_in_threadpool(control.auth.authenticate, request.cookies.get(COOKIE_NAME),
                                                              request.headers.get("x-csrf-token"), mutation)
            if mutation:
                public_api = path == PUBLIC_API or path.startswith(PUBLIC_API + "/")
                header = "x-jbsl-public" if public_api else "x-jbsl-admin"
                if public_api and not origin:
                    raise ApiProblem(403, "origin_required", "公開一覧の画面から操作してください。")
                if request.headers.get(header) != "1" or request.headers.get("sec-fetch-site") == "cross-site":
                    raise ApiProblem(403, "public_header_required" if public_api else "admin_header_required",
                                     "公開一覧の画面から操作してください。" if public_api else "管理画面から操作してください。")
                if request.headers.get("content-type", "").split(";")[0] != "application/json":
                    raise ApiProblem(415, "json_required", "JSON が必要です。")
            response = await call_next(request)
        except ApiProblem as exc:
            response = problem_response(exc)
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                                 "X-JBSL-Mock-Server": "true", "Referrer-Policy": "no-referrer",
                                 "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"})
        return response

    async def payload(request, limit=1024 * 1024):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > limit:
                raise ApiProblem(413, "body_too_large", "リクエストのサイズが上限を超えています。")
        try:
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, UnicodeError) as exc:
            raise ApiProblem(400, "invalid_json", "JSON object が必要です。") from exc

    app.include_router(public_qualifier_router(control, payload))

    @app.get("/", include_in_schema=False)
    async def index():
        return RedirectResponse("/admin/")

    @app.get("/admin/")
    async def admin():
        return FileResponse(ROOT / "static/index.html")

    @app.get("/guide")
    async def guide():
        return FileResponse(ROOT / "static/guide.html")

    @app.get("/healthz")
    async def health():
        return {"ok": True, "role": "relay-admin", "testOnly": True}

    @app.post("/admin/api/login")
    async def login(request: Request):
        body = await payload(request, limit=4096)
        if set(body) != {"username", "password"}:
            raise ApiProblem(400, "invalid_login_fields", "ユーザー名とパスワードを入力してください。")
        token, info = await run_in_threadpool(control.auth.login, body["username"], body["password"],
                                              request.client.host if request.client else "unknown", request.cookies.get(COOKIE_NAME))
        response = JSONResponse(info)
        response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, path="/admin", httponly=True,
                            secure=request.url.scheme == "https", samesite="strict")
        return response

    @app.get("/admin/api/me")
    async def me(request: Request):
        return request.state.admin

    @app.post("/admin/api/logout")
    async def logout(request: Request):
        await run_in_threadpool(control.auth.logout, request.cookies.get(COOKIE_NAME))
        response = Response(status_code=204)
        response.delete_cookie(COOKIE_NAME, path="/admin", httponly=True,
                               secure=request.url.scheme == "https", samesite="strict")
        return response

    @app.get("/admin/api/overview")
    async def overview():
        state = control.snapshot()
        urls = control.browser_urls
        public_mode = bool(control.base_settings.public_url)
        result = {"urls": urls, "publicMode": public_mode, "upstream": "https://jbsl-web.herokuapp.com/api/active_league",
                "behavior": state["behavior"], "generation": state["generation"],
                "serverTime": utc_text(utc_now()), "wallTime": utc_text(utc_now()),
                "viewerConfig": {"leaderboardApiUrl": urls["proxy"] + "/leaderboard/api/",
                                 "allowDevelopmentHttp": not public_mode},
                "logCapacity": control.log.rows.maxlen}
        if not public_mode:
            result["dataDirectory"] = str(control.data_dir)
        return result

    @app.get("/admin/api/leagues")
    async def leagues():
        state = control.snapshot()
        registered = [{"id": int(key), "name": entry["upstream"]["league_title"], "source": entry["source"],
                       "enabled": entry["fixture"]["qualifier"]["enabled"], "isOpen": entry["fixture"]["isOpen"],
                       "revision": entry["fixture"]["qualifier"]["revision"], "mapCount": len(entry["fixture"]["maps"])}
                      for key, entry in state["leagues"].items()]
        return {"active": state["active"], "registered": registered}

    @app.post("/admin/api/leagues/refresh")
    async def refresh():
        return await control.refresh_active()

    @app.post("/admin/api/leagues/{league_id}/import")
    async def import_league(league_id: int):
        entry = await control.import_league(league_id)
        return {"entry": entry, "expectedRevision": None, "rankingSids": ranking_sids(entry["upstream"])}

    @app.get("/admin/api/leagues/{league_id}")
    async def league(league_id: int):
        entry = await control.league_for_edit(league_id)
        return {"entry": entry, "expectedRevision": entry["fixture"]["qualifier"]["revision"],
                "rankingSids": ranking_sids(entry["upstream"])}

    async def save(request, league_id, preview=False):
        body = await payload(request)
        if set(body) != {"fixture", "expectedRevision"} or not isinstance(body["fixture"], dict):
            raise ApiProblem(400, "invalid_settings", "fixture と expectedRevision が必要です。")
        result = control.save_league(league_id, body["fixture"], body["expectedRevision"], preview=preview)
        await control.scoresaber.fill(result["merged"])
        return result

    @app.put("/admin/api/leagues/{league_id}")
    async def save_league(request: Request, league_id: int):
        return await save(request, league_id)

    @app.post("/admin/api/leagues/{league_id}/preview")
    async def preview(request: Request, league_id: int):
        return await save(request, league_id, True)

    @app.put("/admin/api/settings")
    async def save_settings(request: Request):
        body = await payload(request)
        try:
            if set(body) != {"behavior", "generation"} or type(body["generation"]) is not int:
                raise ValueError("behavior と整数の generation が必要です。")
            control.save_behavior(Behavior.model_validate(body["behavior"]), body["generation"])
        except (ValidationError, ValueError) as exc:
            raise ApiProblem(422, "invalid_settings", str(exc)) from exc
        return {"saved": True, "generation": control.snapshot()["generation"]}

    @app.get("/admin/api/logs")
    async def logs(role: str = "all", errors: bool = False, after: int = 0):
        return {"items": control.log.read(role, errors, after), "capacity": control.log.rows.maxlen}

    @app.get("/admin/api/probe/{league_id}")
    async def probe(league_id: int):
        if league_id <= 0:
            raise ApiProblem(400, "invalid_league", "リーグ ID は正の整数です。")
        try:
            async with httpx.AsyncClient(timeout=65, trust_env=False) as client:
                response = await client.get(control.urls["proxy"] + f"/leaderboard/api/{league_id}")
            try:
                body = response.json()
            except ValueError:
                body = response.text[:4096]
            return {"status": response.status_code, "body": body}
        except httpx.HTTPError as exc:
            raise ApiProblem(503, "proxy_unavailable", "中継サーバへ接続できません。") from exc

    @app.post("/admin/api/logs/clear")
    async def clear_logs():
        control.log.clear()
        return {"cleared": True}

    @app.get("/admin/api/state")
    async def state():
        with control.proxy_app.state.count_lock:
            counts = copy.deepcopy(control.proxy_app.state.counts)
        return {"requests": {"proxy": counts}, "registeredLeagues": len(control.snapshot()["leagues"])}

    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    return app

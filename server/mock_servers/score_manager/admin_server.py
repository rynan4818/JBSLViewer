"""No-login, loopback-only administration listener."""
from __future__ import annotations

import copy
import json

from typing import Literal
from fastapi import FastAPI, Query, Request
from .inspection import Inspector
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .config import ROOT, utc_now
from .control import Behavior, Control, SettingsView
from .errors import ApiProblem, problem_response
from .schemas import utc_text


def make_apps(control: Control):
    from .score_manager_server import create_app as score_app
    control.score_app = score_app(SettingsView(control), control=control)
    return create_app(control), control.score_app


def create_app(control: Control):
    app = FastAPI(title="Debug Score Manager Control", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.control = control
    inspector = Inspector(control)

    @app.exception_handler(ApiProblem)
    async def problem(_, exc):
        return problem_response(exc)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if request.url.hostname not in {"127.0.0.1", "localhost", "testserver"}:
            return problem_response(ApiProblem(403, "local_only", "ローカル管理画面です。"))
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            return problem_response(ApiProblem(403, "cross_origin", "別サイトからの管理操作は許可されません。"))
        if request.method not in {"GET", "HEAD"}:
            if request.headers.get("x-jbsl-admin") != "1" or request.headers.get("sec-fetch-site") == "cross-site":
                return problem_response(ApiProblem(403, "admin_header_required", "管理画面から操作してください。"))
            if request.headers.get("content-type", "").split(";")[0] != "application/json":
                return problem_response(ApiProblem(415, "json_required", "JSON が必要です。"))
        response = await call_next(request)
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                                 "X-JBSL-Mock-Server": "true", "Referrer-Policy": "no-referrer",
                                 "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"})
        return response

    async def payload(request):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 1024 * 1024:
                raise ApiProblem(413, "body_too_large", "管理設定は1 MiB以下にしてください。")
        try:
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, UnicodeError) as exc:
            raise ApiProblem(400, "invalid_json", "JSON object が必要です。") from exc

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
        return {"ok": True, "role": "score-admin", "testOnly": True}

    @app.get("/admin/api/overview")
    async def overview():
        state = control.snapshot()
        return {"urls": control.urls,
                "behavior": state["behavior"], "generation": state["generation"],
                "serverTime": utc_text(control.score_settings().clock()), "wallTime": utc_text(utc_now()),
                "viewerConfig": {"scoreServerBaseUrl": control.urls["score"], "allowDevelopmentHttp": True},
                "dataDirectory": str(control.data_dir), "logCapacity": control.log.rows.maxlen}

    @app.put("/admin/api/settings")
    async def save_settings(request: Request):
        body = await payload(request)
        try:
            if set(body) != {"behavior", "generation"} or type(body["generation"]) is not int:
                raise ValueError("behavior と整数の generation が必要です。")
            value = Behavior.model_validate(body["behavior"])
            if value.upstream_base_url in control.urls.values():
                raise ValueError("リーグ取得先にこのスコアAPIや管理画面自身は指定できません。")
            control.save_behavior(value, body["generation"])
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
        board = await control.score_app.state.client.get_async(league_id)
        return {"leagueId": board["league_id"], "name": board["league_title"],
                "qualifier": board["qualifier"], "mapCount": len(board["maps"])}

    @app.post("/admin/api/logs/clear")
    async def clear_logs():
        control.log.clear()
        return {"cleared": True}

    @app.get("/admin/api/state")
    async def state():
        result = await run_in_threadpool(inspector.state)
        with control.score_app.state.count_lock:
            result["requests"] = copy.deepcopy(control.score_app.state.counts)
        return result

    @app.get("/admin/api/challenges")
    async def challenges(status: Literal["all", "reserved", "started", "submitted", "abandoned"] = "all",
                         league_id: int | None = Query(None, gt=0), sid: str = Query("", max_length=128),
                         q: str = Query("", max_length=128), page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)):
        return await run_in_threadpool(inspector.challenges, status=status, league_id=league_id, sid=sid, q=q, page=page, page_size=page_size)

    @app.get("/admin/api/challenges/{challenge_id}")
    async def challenge(challenge_id: str):
        return await run_in_threadpool(inspector.challenge, challenge_id)

    @app.get("/admin/api/results")
    async def results(ranking: Literal["all", "valid", "invalid"] = "all",
                      end_type: Literal["all", "clear", "fail", "quit", "restart", "unknown", "preflight_rejected"] = "all",
                      league_id: int | None = Query(None, gt=0), sid: str = Query("", max_length=128),
                      q: str = Query("", max_length=128), page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)):
        return await run_in_threadpool(inspector.results, ranking=ranking, end_type=end_type, league_id=league_id, sid=sid, q=q, page=page, page_size=page_size)

    @app.get("/admin/api/results/{result_id}")
    async def result(result_id: str):
        return await run_in_threadpool(inspector.result, result_id)

    @app.get("/admin/api/budgets")
    async def budgets(league_id: int | None = Query(None, gt=0), sid: str = Query("", max_length=128),
                      page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)):
        return await run_in_threadpool(inspector.budgets, league_id=league_id, sid=sid, page=page, page_size=page_size)

    @app.get("/admin/api/audit")
    async def audit(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)):
        return await run_in_threadpool(inspector.audit, page=page, page_size=page_size)

    @app.post("/admin/api/actions/{action}")
    async def action(action: str):
        def execute():
            with control.score_app.state.db.connect() as db:
                if action == "clear-cache":
                    db.execute("DELETE FROM league_qualifier_caches")
                elif action == "expire-sessions":
                    db.execute("UPDATE sessions SET revoked_at=? WHERE revoked_at IS NULL", (utc_text(utc_now()),))
                elif action == "clear-rate-limits":
                    with control.score_app.state.rate_limiter.lock:
                        control.score_app.state.rate_limiter.events.clear()
                else:
                    raise ApiProblem(404, "unknown_action", "不明な操作です。")
        await run_in_threadpool(execute)
        control.log.add(role="admin", method="POST", path=f"/admin/api/actions/{action}", status=200, source="local")
        return {"done": action}

    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    return app

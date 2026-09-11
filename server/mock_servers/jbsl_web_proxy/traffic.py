"""ASGI observation and fault injection without consuming replay streams."""
import asyncio
import json
import re
import time
from uuid import uuid4

from starlette.responses import Response

from .control import request_id
from .config import prepare_http_scope
from .errors import ApiProblem, problem_response


class DebugTraffic:
    def __init__(self, app, *, control, role):
        self.app, self.control, self.role = app, control, role

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        observed = path.startswith("/leaderboard/api/") if self.role == "proxy" else path.startswith("/api/v1/")
        if not observed:
            return await self.app(scope, receive, send)
        if not prepare_http_scope(scope, self.control.base_settings.public_url):
            return await self.app(scope, receive, send)
        state = self.control.snapshot()
        token = self.control.context.set(state)
        headers = dict(scope["headers"])
        supplied = headers.get(b"x-request-id", b"").decode("ascii", errors="ignore")
        trace = supplied if re.fullmatch(r"[a-fA-F0-9-]{36}", supplied) else str(uuid4())
        trace_token = request_id.set(trace)
        scope.setdefault("state", {})["mock_request_id"] = trace
        started, status, error, head = time.monotonic(), 500, None, bytearray()
        behavior = state["behavior"]
        fault = behavior[f"{self.role}_fault"]
        delay = behavior[f"{self.role}_delay_ms"]
        if self.role == "score":
            route = "auth" if "/auth/" in path else ("reserve" if path.endswith("/challenges") else path.rsplit("/", 1)[-1])
            if behavior["score_fault_route"] not in {"all", route}:
                fault, delay = "none", 0

        async def observe(message):
            nonlocal status, error
            if message["type"] == "http.response.start":
                status = message["status"]
                outgoing = [(k, v) for k, v in message["headers"] if k.lower() != b"x-request-id"]
                message = {**message, "headers": outgoing + [(b"x-request-id", trace.encode())]}
            elif message["type"] == "http.response.body" and status >= 400:
                head.extend(message.get("body", b"")[:max(0, 4096 - len(head))])
            await send(message)

        try:
            if delay:
                await asyncio.sleep(delay / 1000)
            if fault == "upstream_invalid":
                error = "upstream_invalid"
                await Response("{invalid", media_type="application/json", headers={"X-JBSL-Mock-Server": "true"})(scope, receive, observe)
            elif fault != "none":
                codes = {"upstream_unavailable": (503, "upstream_unavailable"), "unavailable": (503, "internal_error"),
                         "authentication_required": (401, "authentication_required"), "rate_limited": (429, "rate_limited"),
                         "not_found": (404, "league_not_found")}
                code, error = codes[fault]
                await problem_response(ApiProblem(code, error, "管理画面で設定したデバッグ用の障害です。"), trace)(scope, receive, observe)
            else:
                await self.app(scope, receive, observe)
        finally:
            if head:
                try:
                    error = json.loads(head).get("error", {}).get("code") or error
                except (ValueError, AttributeError):
                    pass
            # Paths use only fixed route names, numeric league IDs and UUIDs.
            safe_path = re.sub(r"[^a-zA-Z0-9/_-]", "_", path)[:200]
            self.control.log.add(role=self.role, method=scope["method"], path=safe_path, status=status,
                                 elapsedMs=round((time.monotonic() - started) * 1000, 1), errorCode=error,
                                 source=("injected" if fault != "none" else self.source(state, path)))
            request_id.reset(trace_token)
            self.control.context.reset(token)

    def source(self, state, path):
        if self.role == "score":
            return "local"
        entry = state["leagues"].get(path.rsplit("/", 1)[-1])
        if entry is None:
            return "live"
        if entry and entry["source"] == "sample":
            return "sample"
        return state["behavior"]["upstream_mode"]

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.requests import ClientDisconnect

from .contracts import strict_json
from .errors import ApiProblem, problem_response
from .replay_viewer import PUBLIC_REPLAY_PATH_PATTERN, REPLAY_PATH_PATTERN, VIEWER_ORIGINS
from .timing import elapsed_ms, measure_operation

LOG = logging.getLogger("jbsl_score")


class Guard:
    def __init__(self, app, service, kind):
        self.app, self.service, self.kind = app, service, kind

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        with measure_operation(request_id=str(uuid4())) as timing:
            scope.setdefault("state", {})["audit_timing"] = timing
            scope["state"]["request_id"] = timing.request_id
            return await self._http(scope, receive, send)

    async def _http(self, scope, receive, send):
        config = self.service.config
        request_id = scope["state"]["request_id"]
        headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope["headers"]}
        public = urlsplit(getattr(config, self.kind + "_public_url"))
        allowed_hosts = {
            public.netloc.lower(),
            f"127.0.0.1:{getattr(config, self.kind + '_port')}",
            f"localhost:{getattr(config, self.kind + '_port')}",
        }
        origin = headers.get("origin")
        path = scope["path"]
        replay_request = (
            self.kind == "api" and scope["method"] in ("GET", "OPTIONS")
            and (REPLAY_PATH_PATTERN.fullmatch(path) is not None or PUBLIC_REPLAY_PATH_PATTERN.fullmatch(path) is not None)
            and (origin is None or origin in VIEWER_ORIGINS)
        )
        error = None
        if headers.get("host", "").lower() not in allowed_hosts:
            error = ApiProblem(400, "invalid_host", "Host header is not configured for this listener.")
        elif self.kind == "api" and not replay_request and (
            origin is not None or headers.get("sec-fetch-site") == "cross-site"
        ):
            error = ApiProblem(403, "browser_request_rejected", "This API is for native and server clients.")
        elif self.kind == "admin" and origin is not None and origin != public.geturl().rstrip("/"):
            error = ApiProblem(403, "csrf_rejected", "Origin is not permitted.")
        elif public.scheme == "https" and scope["scheme"] != "https":
            error = ApiProblem(403, "https_required", "HTTPS is required.")
        total, started, sent = 0, scope["state"]["audit_timing"].started, False
        limit = (
            config.compressed_replay_limit + config.metadata_limit + 16384
            if path.endswith("/result") and self.kind == "api"
            else config.metadata_limit
        )

        async def bounded_receive():
            nonlocal total
            remaining = config.request_timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise ApiProblem(408, "request_timeout", "Request upload timed out.", retryable=True)
            try:
                message = await asyncio.wait_for(receive(), timeout=remaining)
            except TimeoutError:
                raise ApiProblem(408, "request_timeout", "Request upload timed out.", retryable=True) from None
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > limit:
                    raise ApiProblem(
                        413,
                        "replay_too_large" if path.endswith("/result") else "malformed_request",
                        "Request body exceeds the configured limit.",
                    )
            return message

        async def guarded_send(message):
            nonlocal sent
            if message["type"] == "http.response.start":
                sent = True
                csp = b"default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
                if self.kind == "admin" and path in ("/admin/docs", "/admin/docs/"):
                    # Swagger's bundled CSS uses data-URI icons. Keep this exception on its HTML only.
                    csp += b"; img-src 'self' data:"
                extra = [
                    (b"cache-control", b"no-store"),
                    (b"x-request-id", request_id.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (
                        b"content-security-policy",
                        csp,
                    ),
                ]
                if public.scheme == "https":
                    extra.append((b"strict-transport-security", b"max-age=31536000"))
                viewer_origin = scope["state"].get("replay_viewer_origin")
                if replay_request and viewer_origin:
                    extra.extend([(b"access-control-allow-origin", viewer_origin.encode()), (b"vary", b"Origin")])
                names = {k for k, _ in extra}
                message["headers"] = [(k, v) for k, v in message.get("headers", []) if k.lower() not in names] + extra
            await send(message)

        if error:
            response = await report_problem(Request(scope), error, self.service)
            return await response(scope, receive, guarded_send)
        try:
            length = headers.get("content-length")
            if length is not None and (len(length) > 18 or not length.isascii() or not length.isdecimal()):
                raise ApiProblem(400, "malformed_request", "Invalid Content-Length.")
            if length and int(length) > limit:
                # Result auth/owner/deadline precedence is preserved in the endpoint.
                if not path.endswith("/result"):
                    raise ApiProblem(413, "malformed_request", "Request body exceeds the configured limit.")
            await self.app(scope, bounded_receive, guarded_send)
        except ApiProblem as problem:
            if not sent:
                response = await report_problem(Request(scope), problem, self.service)
                await response(scope, receive, guarded_send)
            else:
                raise


async def json_body(request: Request):
    if request.headers.get("content-type", "").split(";")[0].lower() != "application/json":
        raise ApiProblem(400, "malformed_request", "Content-Type must be application/json.")
    try:
        return strict_json(await request.body())
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise ApiProblem(400, "malformed_request", "Body must be valid JSON without duplicate fields.") from None


async def report_problem(request, error, service):
    # ServerErrorMiddleware may invoke this after Guard has exited; restore this request's timing.
    with measure_operation(timing=getattr(request.state, "audit_timing", None)):
        request_id = getattr(request.state, "request_id", str(uuid4()))
        actor = getattr(request.state, "actor", "anonymous")
        challenge_id = getattr(request.state, "challenge_id", None)
        route = getattr(request.scope.get("route"), "path", "unmatched")
        # Only server-controlled codes and route templates enter logs; no URLs, tickets or bodies.
        LOG.info("request_failed request_id=%s status=%s code=%s route=%s elapsed_ms=%s",
                 request_id, error.status, error.code, route, elapsed_ms())
        if error.status != 429:
            try:
                await run_in_threadpool(
                    service.db.audit,
                    service.clock(),
                    actor,
                    "request_rejected",
                    challenge_id,
                    request_id,
                    {"status": error.status, "code": error.code, "route": route},
                )
            except sqlite3.Error:
                LOG.error("audit_write_failed request_id=%s", request_id)
        return problem_response(error, request_id)


def install_errors(app, service):
    @app.exception_handler(ApiProblem)
    async def problem(request, error):
        return await report_problem(request, error, service)

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(HTTPException)
    async def invalid(request, error):
        return await problem(
            request, ApiProblem(getattr(error, "status_code", 400), "malformed_request", "Request is invalid.")
        )

    @app.exception_handler(sqlite3.OperationalError)
    async def database_busy(request, error):
        return await problem(request, ApiProblem(503, "storage_unavailable", "Database is temporarily unavailable."))

    @app.exception_handler(ClientDisconnect)
    async def disconnected(request, error):
        return await problem(request, ApiProblem(408, "request_timeout", "Request was interrupted.", retryable=True))

    @app.exception_handler(Exception)
    async def unexpected(request, error):
        LOG.error(
            "internal_error type=%s request_id=%s",
            type(error).__name__,
            getattr(request.state, "request_id", "unknown"),
        )
        return await problem(request, ApiProblem(500, "internal_error", "An internal error occurred."))

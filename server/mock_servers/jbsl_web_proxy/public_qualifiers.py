"""Anonymous Qualifier catalog and append-only participant registration."""
from __future__ import annotations

import threading
import time
from collections import deque

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from .config import ROOT
from .errors import ApiProblem

PUBLIC_API = "/public/api/qualifier-leagues"


class ParticipantRateLimit:
    def __init__(self):
        self.lock = threading.Lock()
        self.requests = {}
        self.clock = time.monotonic

    def check(self, identity):
        now = self.clock()
        with self.lock:
            for key, requests in list(self.requests.items()):
                while requests and requests[0] <= now - 60:
                    requests.popleft()
                if not requests:
                    del self.requests[key]
            requests = self.requests.setdefault(identity, deque())
            if len(requests) >= 10:
                raise ApiProblem(429, "rate_limited", "SIDの追加要求が多すぎます。1分ほど待ってから再試行してください。")
            requests.append(now)


def create_router(control, payload):
    router = APIRouter()
    limiter = ParticipantRateLimit()

    @router.get("/qualifiers/", include_in_schema=False)
    async def page():
        return FileResponse(ROOT / "static/qualifiers.html")

    @router.get(PUBLIC_API)
    async def leagues():
        await control.refresh_public_active()
        return control.public_qualifiers()

    @router.post(PUBLIC_API + "/{league_id}/participants")
    async def add_participant(request: Request, league_id: int):
        status, code = 500, "internal_error"
        started = time.monotonic()
        try:
            limiter.check(request.client.host if request.client else "unknown")
            body = await payload(request, limit=1024)
            if set(body) != {"sid"}:
                raise ApiProblem(400, "invalid_participant_fields", "追加するSIDだけを指定してください。")
            sid = control.normalize_public_sid(body["sid"])
            await control.refresh_public_active()
            result = await run_in_threadpool(control.add_public_participant, league_id, sid)
            status, code = 200, None
            return result
        except OSError as exc:
            status, code = 503, "participant_save_failed"
            raise ApiProblem(status, code, "SIDを保存できませんでした。時間を置いて再試行してください。") from exc
        except ApiProblem as exc:
            status, code = exc.status, exc.code
            raise
        finally:
            control.log.add(role="public", method="POST", path=f"{PUBLIC_API}/{league_id}/participants",
                            status=status, errorCode=code, source="public", elapsedMs=round((time.monotonic()-started)*1000, 1))

    return router

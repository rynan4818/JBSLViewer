from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from .errors import ApiProblem
from .schemas import validate_projection


def _headers():
    from .control import request_id
    trace = request_id.get()
    return {"Accept": "application/json", **({"X-Request-ID": trace} if trace else {})}


def _convert_response(response: httpx.Response) -> dict[str, Any]:
    if response.status_code == 404:
        raise ApiProblem(404, "league_not_found", "League does not exist.")
    if response.status_code in {409, 400}:
        raise ApiProblem(502, "upstream_invalid", "The upstream leaderboard response is invalid.")
    if response.status_code >= 500:
        raise ApiProblem(503, "upstream_unavailable", "The upstream leaderboard is unavailable.")
    if response.status_code != 200:
        raise ApiProblem(502, "upstream_invalid", "The upstream leaderboard response is invalid.")
    try:
        return validate_projection(response.json())
    except (ValueError, json.JSONDecodeError) as exc:
        raise ApiProblem(502, "upstream_invalid", "The upstream leaderboard response is invalid.") from exc


class LeaderboardClient:
    def __init__(self, settings, *, control=None):
        self.settings = settings
        self.control = control

    def options(self):
        base = self.settings if isinstance(self.settings, str) else self.settings.upstream_base_url
        timeout = 10 if isinstance(self.settings, str) else self.settings.upstream_timeout_seconds
        return base.rstrip("/"), timeout, urlsplit(base).hostname not in {"127.0.0.1", "localhost", "::1"}

    def record(self, league_id, base, started, status, error):
        if self.control:
            self.control.log.add(role="upstream", method="GET", path=f"/leaderboard/api/{league_id}",
                                 status=status, errorCode=error, source=base,
                                 elapsedMs=round((time.monotonic() - started) * 1000, 1))

    async def get_async(self, league_id: int) -> dict[str, Any]:
        base, timeout, trust_env = self.options()
        started, status, error = time.monotonic(), 503, None
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=trust_env) as client:
                response = await client.get(f"{base}/leaderboard/api/{league_id}", headers=_headers())
            status = response.status_code
            return _convert_response(response)
        except httpx.HTTPError as exc:
            error = "upstream_unavailable"
            raise ApiProblem(503, "upstream_unavailable", "The upstream leaderboard is unavailable.") from exc
        except ApiProblem as exc:
            error = exc.code
            raise
        finally:
            self.record(league_id, base, started, status, error)

    def get_sync(self, league_id: int) -> dict[str, Any]:
        base, timeout, trust_env = self.options()
        started, status, error = time.monotonic(), 503, None
        try:
            with httpx.Client(timeout=timeout, trust_env=trust_env) as client:
                response = client.get(f"{base}/leaderboard/api/{league_id}", headers=_headers())
            status = response.status_code
            return _convert_response(response)
        except httpx.HTTPError as exc:
            error = "upstream_unavailable"
            raise ApiProblem(503, "upstream_unavailable", "The upstream leaderboard is unavailable.") from exc
        except ApiProblem as exc:
            error = exc.code
            raise
        finally:
            self.record(league_id, base, started, status, error)

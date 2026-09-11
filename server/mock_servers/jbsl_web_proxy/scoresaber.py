"""Optional participant names from ScoreSaber's fixed-origin public API."""
from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future

import httpx


def valid_name(sid, name):
    if (isinstance(sid, str) and 1 <= len(sid) <= 128 and re.fullmatch(r"\S+", sid)
            and isinstance(name, str) and 1 <= len(name) <= 200 and name.strip() and name.strip() != sid
            and not any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in sid + name)):
        return name.strip()
    return None


def total_rank_names(board):
    names = {}
    ranking = board.get("total_rank")
    if isinstance(ranking, list):
        for row in ranking:
            if isinstance(row, dict) and (name := valid_name(row.get("sid"), row.get("name"))):
                names.setdefault(row["sid"], name)
    return names


class ScoreSaber:
    def __init__(self, log=None, transport=None, *, clock=time.monotonic, fill_timeout=3.0):
        self.log, self.transport, self.clock = log, transport, clock
        self.fill_timeout = fill_timeout
        self._lock = threading.Lock()
        self._cache = OrderedDict()
        # concurrent.futures.Future can be awaited by both admin and proxy event loops.
        self._pending: dict[str, Future] = {}

    def _store(self, sid, name, retry_at):
        self._cache[sid] = (name, retry_at)
        self._cache.move_to_end(sid)
        while len(self._cache) > 4096:
            self._cache.popitem(last=False)

    def cached_name(self, sid):
        with self._lock:
            return self._cache.get(sid, (None, 0))[0] or sid

    async def _fetch(self, sid):
        path = f"/api/v2/players/{sid}"
        started, status, error = time.monotonic(), 503, None
        try:
            async with asyncio.timeout(self.fill_timeout):
                async with httpx.AsyncClient(timeout=httpx.Timeout(3, connect=2), transport=self.transport,
                                             follow_redirects=False) as client:
                    async with client.stream("GET", "https://scoresaber.com" + path,
                                             headers={"Accept": "application/json", "User-Agent": "JBSL-Web-Relay/1.0"}) as response:
                        status = response.status_code
                        if status != 200:
                            error = "scoresaber_unavailable"
                            return None
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            data.extend(chunk)
                            if len(data) > 2 * 1024 * 1024:
                                raise ValueError("response too large")
                profile = json.loads(data)
                if not isinstance(profile, dict) or profile.get("id") != sid:
                    raise ValueError("player ID mismatch")
                name = valid_name(sid, profile.get("name"))
                if name is None:
                    raise ValueError("invalid name")
                return name
        except (httpx.HTTPError, TimeoutError):
            error = "scoresaber_unavailable"
        except (ValueError, TypeError, RecursionError):
            error = "scoresaber_invalid"
        except asyncio.CancelledError:
            error = "scoresaber_timeout"
            raise
        finally:
            if self.log is not None:
                self.log.add(role="upstream", method="GET", path=path, status=status,
                             elapsedMs=round((time.monotonic() - started) * 1000, 1),
                             source="scoresaber", errorCode=error)
        return None

    async def name(self, sid):
        # ScoreSaber IDs are decimal strings (Steam and Oculus). Keep test/custom SIDs intact.
        if not isinstance(sid, str) or re.fullmatch(r"[0-9]{1,128}", sid) is None:
            return sid
        while True:
            with self._lock:
                cached, retry_at = self._cache.get(sid, (None, 0))
                if self.clock() < retry_at:
                    return cached or sid
                future = self._pending.get(sid)
                owner = future is None and len(self._pending) < 4
                if owner:
                    future = self._pending[sid] = Future()
            if future is not None:
                break
            await asyncio.sleep(0.01)
        if not owner:
            return await asyncio.shield(asyncio.wrap_future(future))
        name = None
        try:
            name = await self._fetch(sid)
        finally:
            with self._lock:
                previous = self._cache.get(sid, (None, 0))[0]
                self._store(sid, name or previous, self.clock() + (3600 if name else 60))
                self._pending.pop(sid)
                future.set_result(name or previous or sid)
        return future.result()

    async def fill(self, board):
        """Enrich only the merged copy, keeping input fixtures and rankings unchanged."""
        names = total_rank_names(board)
        tasks = {}
        for participant in board["participants"]:
            sid = participant["sid"]
            if sid in names:
                participant["name"] = names[sid]
                with self._lock:
                    # Keep ranking names as a fallback; ScoreSaber will be tried if the ranking disappears.
                    self._store(sid, names[sid], 0)
            else:
                participant["name"] = self.cached_name(sid)
                if sid not in tasks:
                    tasks[sid] = asyncio.create_task(self.name(sid))
        if tasks:
            try:
                await asyncio.wait(tasks.values(), timeout=self.fill_timeout)
            finally:
                for task in tasks.values():
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks.values(), return_exceptions=True)
            for participant in board["participants"]:
                sid = participant["sid"]
                if sid in tasks:
                    task = tasks[sid]
                    participant["name"] = (task.result() if not task.cancelled() and task.exception() is None
                                           else self.cached_name(sid))
        return board

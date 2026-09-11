"""Read song durations from BeatSaver's public, fixed-origin hash endpoint."""
from __future__ import annotations

import asyncio
import json
import math
import re
import time

import httpx

from .errors import ApiProblem


class BeatSaver:
    def __init__(self, log, transport=None):
        self.log = log
        self.transport = transport
        self.durations: dict[str, int | float] = {}

    async def duration(self, song_hash):
        normalized = song_hash.strip().upper() if isinstance(song_hash, str) else ""
        if not re.fullmatch(r"[0-9A-F]{40}", normalized):
            raise ApiProblem(502, "beatsaver_invalid", "BeatSaver の取得に必要な40桁の hash が不正です。")
        if normalized in self.durations:
            return self.durations[normalized]
        path = f"/maps/hash/{normalized}"
        started = time.monotonic()
        status, error = 503, None
        try:
            async with httpx.AsyncClient(timeout=10, transport=self.transport, follow_redirects=False) as client:
                async with client.stream("GET", "https://api.beatsaver.com" + path,
                                         headers={"Accept": "application/json", "User-Agent": "JBSL-Web-Relay/1.0"}) as response:
                    status = response.status_code
                    if status != 200:
                        raise ApiProblem(502, "beatsaver_unavailable", f"BeatSaver が HTTP {status} を返しました。")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 16 * 1024 * 1024:
                            raise ValueError("response too large")
            metadata = json.loads(data)["metadata"]
            duration = metadata["duration"]
            if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
                raise ValueError("invalid duration")
            self.durations[normalized] = duration
            return duration
        except httpx.HTTPError as exc:
            error = "beatsaver_unavailable"
            raise ApiProblem(503, error, "BeatSaver へ接続できません。") from exc
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            error = "beatsaver_invalid"
            raise ApiProblem(502, error, "BeatSaver の metadata.duration が正の秒数ではありません。") from exc
        except ApiProblem as exc:
            error = exc.code
            raise
        finally:
            self.log.add(role="upstream", method="GET", path=path, status=status,
                         elapsedMs=round((time.monotonic() - started) * 1000, 1),
                         source="beatsaver", errorCode=error)

    async def fill(self, board, fixture, *, missing_only=False):
        """Update an editable copy; failed lookups retain its existing values."""
        if not isinstance(board, dict) or not isinstance(board.get("maps"), list) or any(not isinstance(m, dict) for m in board["maps"]):
            return []  # Let the leaderboard validation report malformed upstream data.
        targets = {}
        notes = []
        for index, patch in enumerate(fixture["maps"]):
            if missing_only and patch["song_duration_seconds"] is not None:
                continue
            if "lid" in patch:
                matches = [m for m in board["maps"] if str(m.get("lid")) == str(patch["lid"])]
            else:
                selector = patch.get("index")
                matches = [board["maps"][selector]] if type(selector) is int and 0 <= selector < len(board["maps"]) else []
            if len(matches) != 1:
                continue  # The normal fixture validation reports selector errors.
            raw_hash = matches[0].get("hash")
            song_hash = raw_hash.strip().upper() if isinstance(raw_hash, str) else ""
            targets.setdefault(song_hash, []).append((index, patch))
        semaphore = asyncio.Semaphore(4)

        async def fetch(song_hash):
            async with semaphore:
                try:
                    return await self.duration(song_hash)
                except ApiProblem as exc:
                    return exc

        results = await asyncio.gather(*(fetch(song_hash) for song_hash in targets))
        for patches, result in zip(targets.values(), results):
            for index, patch in patches:
                if isinstance(result, ApiProblem):
                    notes.append(f"譜面 {index + 1}: 曲時間を取得できませんでした。既存値（未設定なら空欄）を保持します。{result.message}")
                else:
                    patch["song_duration_seconds"] = result
        return notes

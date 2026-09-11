"""Persistent controls for the independent JBSL-WEB relay.

Only this process writes control.json. Each API request sees an immutable settings
snapshot, for the relay's request lifetime.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import threading
import time
from collections import deque
from contextvars import ContextVar
from datetime import timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from .admin_auth import AdminAuth
from .beatsaver import BeatSaver
from .config import ROOT, Settings, utc_now
from .errors import ApiProblem
from .schemas import DIFFICULTIES, parse_utc, utc_text
from .scoresaber import ScoreSaber

UPSTREAM = "https://jbsl-web.herokuapp.com"
request_id: ContextVar[str | None] = ContextVar("mock_request_id", default=None)


class Behavior(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    upstream_mode: Literal["live", "snapshot"] = "live"
    proxy_fault: Literal["none", "upstream_unavailable", "upstream_invalid", "rate_limited", "not_found"] = "none"
    proxy_delay_ms: int = Field(0, ge=0, le=60000)
    participant_helper_sid: str = Field("76561198000000000", min_length=1, max_length=128, pattern=r"^\S+$")


class TrafficLog:
    def __init__(self, capacity=1500):
        self.rows = deque(maxlen=capacity)
        self.lock = threading.Lock()
        self.sequence = 0

    def add(self, **row):
        # Deliberately no HTTP bodies, query strings, cookies or credentials.
        with self.lock:
            self.sequence += 1
            self.rows.append({"id": self.sequence, "time": utc_text(utc_now()),
                              "requestId": request_id.get() or str(uuid4()), **row})

    def read(self, role="all", errors=False, after=0):
        with self.lock:
            return [copy.deepcopy(r) for r in self.rows if r["id"] > after
                    and (role == "all" or r.get("role") == role)
                    and (not errors or r.get("status", 200) >= 400 or r.get("errorCode"))]

    def clear(self):
        with self.lock:
            self.rows.clear()


class PublicJbsl:
    """Fixed-origin read-only client; never forwards Viewer credentials."""
    def __init__(self, log: TrafficLog, transport=None):
        self.log = log
        self.transport = transport

    async def get(self, path: str, *, raw_response=False):
        if not re.fullmatch(r"/(api/active_league|api/playlist_songs/[1-9][0-9]*|leaderboard/api/[1-9][0-9]*)", path):
            raise ValueError("Only the documented public GET endpoints are allowed")
        started = time.monotonic()
        status, error = 503, None
        try:
            async with httpx.AsyncClient(timeout=20, transport=self.transport, follow_redirects=False) as client:
                async with client.stream("GET", UPSTREAM + path, headers={"Accept": "application/json"}) as response:
                    status = response.status_code
                    if status == 404:
                        raise ApiProblem(404, "league_not_found", "実 JBSL-WEB に対象がありません。")
                    if status != 200:
                        raise ApiProblem(503, "upstream_unavailable", f"実 JBSL-WEB が HTTP {status} を返しました。")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 16 * 1024 * 1024:
                            raise ApiProblem(502, "upstream_invalid", "実 JBSL-WEB の応答が16 MiBを超えました。")
            try:
                decoded = json.loads(data)
                return Response(content=bytes(data), media_type="application/json") if raw_response else decoded
            except (ValueError, UnicodeError) as exc:
                raise ApiProblem(502, "upstream_invalid", "実 JBSL-WEB の応答が JSON ではありません。") from exc
        except httpx.HTTPError as exc:
            error = "upstream_unavailable"
            raise ApiProblem(503, error, "実 JBSL-WEB へ接続できません。ネットワーク・証明書・プロキシ設定を確認してください。") from exc
        except ApiProblem as exc:
            error = exc.code
            raise
        finally:
            self.log.add(role="upstream", method="GET", path=path, status=status,
                         elapsedMs=round((time.monotonic() - started) * 1000, 1),
                         source="live", errorCode=error)


class Control:
    def __init__(self, data_dir: Path, *, proxy_port=18080, admin_port=18764, transport=None, public_url=""):
        self.base_settings = Settings(public_url=public_url)
        self.base_settings.validate()
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.auth = AdminAuth(self.data_dir / "admin_auth.sqlite3")
        self.path = self.data_dir / "control.json"
        self.lock = threading.RLock()
        self._active_fetch_lock = asyncio.Lock()
        self._active_retry_after = None
        self._active_refresh_failed = False
        self.context = ContextVar("mock_control_snapshot", default=None)
        self.log = TrafficLog()
        self.public = PublicJbsl(self.log, transport)
        self.beatsaver = BeatSaver(self.log, transport)
        self.scoresaber = ScoreSaber(self.log, transport)
        self.urls = {"proxy": f"http://127.0.0.1:{proxy_port}", "admin": f"http://127.0.0.1:{admin_port}"}
        self.proxy_app = None
        self.drafts: dict[int, dict] = {}
        if self.path.exists():
            state = json.loads(self.path.read_text(encoding="utf-8"))
            if state.get("schemaVersion") != 1:
                raise ValueError("Unknown control.json version")
            Behavior.model_validate(state["behavior"])
            for key, entry in state["leagues"].items():
                self.validate_entry(int(key), entry)
            self.state = state
        else:
            raw = json.loads((ROOT / "fixtures/qualifier_leagues.json").read_text(encoding="utf-8"))
            entries = {}
            for key, fixture in raw["leagues"].items():
                board = json.loads((ROOT / f"fixtures/upstream/leaderboard_{key}.json").read_text(encoding="utf-8"))
                entries[key] = {"fixture": fixture, "upstream": board, "source": "sample", "importedAt": None,
                                "notes": ["同梱の架空サンプルです。実 JBSL-WEB の同番号リーグとは別のデータです。"]}
            self.state = {"schemaVersion": 1, "generation": 1, "behavior": Behavior().model_dump(),
                          "leagues": entries, "active": {"items": [], "fetchedAt": None, "error": None}}
            self._write(self.state)

    @property
    def browser_urls(self):
        return {role: self.base_settings.public_url or url for role, url in self.urls.items()}

    def _write(self, value):
        temporary = self.path.with_suffix(f".{uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(value, handle, ensure_ascii=False, allow_nan=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def commit(self, update):
        with self.lock:
            value = copy.deepcopy(self.state)
            update(value)
            self._write(value)
            self.state = value

    def snapshot(self):
        with self.lock:
            # Snapshots are never mutated; commits replace the whole tree.
            return self.state

    def current(self):
        return self.context.get() or self.snapshot()

    def save_behavior(self, value: Behavior, expected: int):
        def update(state):
            if state["generation"] != expected:
                raise ApiProblem(409, "edit_conflict", "別の画面でサーバ設定が更新されました。再読込してください。")
            state["behavior"] = value.model_dump()
            state["generation"] += 1
        self.commit(update)
        self.log.add(role="admin", method="PUT", path="/admin/api/settings", status=200, source="local")

    def _active_is_fresh(self, state, now):
        active = state["active"]
        return (not self._active_refresh_failed and not active.get("error") and bool(active.get("fetchedAt"))
                and 0 <= (now - parse_utc(active["fetchedAt"])).total_seconds() < 60)

    async def refresh_active(self, *, cached=False):
        async with self._active_fetch_lock:
            state, now = self.snapshot(), utc_now()
            if cached and (state["behavior"]["upstream_mode"] == "snapshot" or self._active_is_fresh(state, now)
                           or (self._active_retry_after is not None and now < self._active_retry_after)):
                return state["active"]
            return await self._fetch_active()

    async def _fetch_active(self):
        try:
            raw = await self.public.get("/api/active_league")
            if not isinstance(raw, list) or len(raw) > 5000:
                raise ValueError("一覧は配列である必要があります。")
            items, seen = [], set()
            for item in raw:
                if not isinstance(item, dict) or type(item.get("id")) is not int or item["id"] <= 0 or item["id"] in seen:
                    raise ValueError("リーグ ID が不正または重複しています。")
                if not isinstance(item.get("name"), str) or type(item.get("isLive")) is not bool or type(item.get("isOpen")) is not bool:
                    raise ValueError("リーグ名・開催状態が不正です。")
                parse_utc(item.get("end"))
                seen.add(item["id"])
                if item["isLive"] and item["isOpen"]:
                    items.append({k: item.get(k) for k in ("id", "name", "end", "isLive", "isOpen", "playlist_id")})
            result = {"items": items, "fetchedAt": utc_text(utc_now()), "error": None}
            self.commit(lambda state: state.update(active=result))
            self._active_refresh_failed = False
            self._active_retry_after = None
            return result
        except (ApiProblem, ValueError, OSError) as exc:
            self._active_refresh_failed = True
            self._active_retry_after = utc_now() + timedelta(seconds=60)
            if isinstance(exc, OSError):
                raise
            error = exc.message if isinstance(exc, ApiProblem) else str(exc)
            self.commit(lambda state: state["active"].update(error=error))
            if isinstance(exc, ApiProblem):
                raise
            raise ApiProblem(502, "upstream_invalid", error) from exc

    async def refresh_public_active(self):
        try:
            await self.refresh_active(cached=True)
        except (ApiProblem, OSError):
            # The public catalog can show the last snapshot, with SID additions disabled.
            pass

    @staticmethod
    def _public_qualifier_entries(state, now):
        for active in state["active"]["items"]:
            entry = state["leagues"].get(str(active["id"]))
            if entry is None or entry["source"] != "live":
                continue
            fixture = entry["fixture"]
            if (active["isLive"] and active["isOpen"] and parse_utc(active["end"]) > now
                    and fixture["qualifier"]["enabled"] and fixture["isLive"] and fixture["isOpen"]
                    and parse_utc(fixture["end"]) > now):
                yield active, entry

    def public_qualifiers(self):
        state, now = self.snapshot(), utc_now()
        snapshot = state["behavior"]["upstream_mode"] == "snapshot"
        stale = not snapshot and not self._active_is_fresh(state, now)
        return {"items": [{"id": active["id"], "name": active["name"],
                           "startsAt": entry["fixture"]["qualifier"]["starts_at"],
                           "endsAt": entry["fixture"]["qualifier"]["ends_at"] or entry["fixture"]["end"]}
                          for active, entry in self._public_qualifier_entries(state, now)],
                "fetchedAt": state["active"]["fetchedAt"], "serverTime": utc_text(now),
                "source": "snapshot" if snapshot else "live", "stale": stale,
                "canAddSid": bool(state["active"]["fetchedAt"]) and not stale}

    @staticmethod
    def normalize_public_sid(sid):
        if isinstance(sid, str):
            sid = sid.strip()
        if (not isinstance(sid, str) or not 1 <= len(sid) <= 128 or not sid.isprintable()
                or any(character.isspace() for character in sid)):
            raise ApiProblem(422, "invalid_sid", "SIDは空白・改行を含まない1〜128文字で入力してください。")
        return sid

    def add_public_participant(self, league_id, sid):
        sid = self.normalize_public_sid(sid)
        with self.lock:
            state, now = self.state, utc_now()
            entry = next((entry for active, entry in self._public_qualifier_entries(state, now)
                          if active["id"] == league_id), None)
            if entry is None:
                raise ApiProblem(404, "qualifier_not_available", "このリーグは現在の公開対象ではありません。一覧を更新してください。")
            if (not state["active"]["fetchedAt"] or (state["behavior"]["upstream_mode"] == "live"
                                                     and not self._active_is_fresh(state, now))):
                raise ApiProblem(503, "active_leagues_unavailable", "開催状況を確認できないため追加できません。時間を置いて一覧を更新してください。")
            revision = entry["fixture"]["qualifier"]["revision"]
            if any(participant["sid"] == sid for participant in entry["fixture"]["participants"]):
                return {"leagueId": league_id, "added": False, "revision": revision}
            revision = str(int(revision) + 1)
            def update(value):
                updated = value["leagues"][str(league_id)]
                updated["fixture"]["participants"].append({"sid": sid})
                updated["fixture"]["qualifier"]["revision"] = revision
                try:
                    self.validate_entry(league_id, updated)
                except (ValueError, KeyError, TypeError, ApiProblem) as exc:
                    raise ApiProblem(409, "qualifier_settings_invalid", "リーグ設定を確認できません。管理者に確認してください。") from exc
            self.commit(update)
        return {"leagueId": league_id, "added": True, "revision": revision}

    async def import_league(self, league_id):
        active = next((v for v in self.snapshot()["active"]["items"] if v["id"] == league_id), None)
        if active is None:
            raise ApiProblem(409, "active_league_missing", "実リーグ一覧を更新し、開催中のリーグを選択してください。")
        board = await self.public.get(f"/leaderboard/api/{league_id}")
        if not isinstance(board, dict) or board.get("league_id") != league_id or not isinstance(board.get("maps"), list) or any(not isinstance(m, dict) for m in board["maps"]):
            raise ApiProblem(502, "upstream_invalid", "leaderboard の形式が不正です。")
        songs, notes = [], []
        playlist = active.get("playlist_id")
        if type(playlist) is int and playlist > 0:
            try:
                songs = await self.public.get(f"/api/playlist_songs/{playlist}")
                if not isinstance(songs, list) or any(not isinstance(s, dict) for s in songs):
                    songs = []
                    notes.append("playlist_songs の形式が不正です。譜面情報を手入力してください。")
            except ApiProblem:
                notes.append("playlist_songs を取得できませんでした。譜面情報を手入力してください。")
        maps = []
        for index, item in enumerate(board["maps"]):
            if not isinstance(item, dict):
                raise ApiProblem(502, "upstream_invalid", "maps の要素が不正です。")
            lid = item.get("lid")
            matches = [s for s in songs if lid is not None and str(s.get("lid")) == str(lid)
                       and str(s.get("hash", "")).strip().upper() == str(item.get("hash", "")).strip().upper()]
            song = matches[0] if len(matches) == 1 else {}
            characteristic = item.get("characteristic") or song.get("char")
            difficulty = item.get("difficulty") or song.get("diff")
            if not characteristic or difficulty not in DIFFICULTIES:
                notes.append(f"譜面 {index + 1}: characteristic / difficulty を確認して入力してください。hash だけでは難易度を推測しません。")
            unique_lid = lid is not None and sum(str(m.get("lid")) == str(lid) for m in board["maps"]) == 1
            maps.append({**({"lid": str(lid)} if unique_lid else {"index": index}),
                         "characteristic": characteristic or "", "difficulty": difficulty or "",
                         "song_duration_seconds": item.get("song_duration_seconds", song.get("song_duration_seconds")),
                         "qualifier_attempt_limit": None})
        entry = {"source": "live", "upstream": board, "importedAt": utc_text(utc_now()), "notes": notes,
                 "fixture": {"isLive": active["isLive"], "isOpen": active["isOpen"], "end": active["end"],
                             "participants": [], "auto_add_ranking_sids": True,
                             "qualifier": {"enabled": False, "submission_method": "external_leaderboard",
                              "revision": "1", "starts_at": None, "ends_at": None}, "maps": maps}}
        notes.extend(await self.beatsaver.fill(board, entry["fixture"]))
        with self.lock:
            self.drafts[league_id] = copy.deepcopy(entry)
        return entry

    async def league_for_edit(self, league_id):
        original = self.snapshot()["leagues"].get(str(league_id))
        if original is None:
            raise ApiProblem(404, "mock_fixture_missing", "未設定のリーグです。")
        entry = copy.deepcopy(original)
        entry["notes"] = [note for note in entry["notes"] if note != "参加者はローカルのテスト用設定です。ランキングの SID から実参加者を推測しません。"]
        if entry["source"] == "live" and self.current()["behavior"]["upstream_mode"] == "live":
            entry["notes"] = [note for note in entry["notes"] if not re.match(r"譜面 \d+: 曲時間を取得できませんでした。", note)]
            entry["notes"].extend(await self.beatsaver.fill(entry["upstream"], entry["fixture"]))
        return entry

    @staticmethod
    def validate_entry(league_id, entry):
        from .jbsl_web_proxy_server import FixtureStore, merge_leaderboard
        fixture = entry["fixture"]
        FixtureStore._validate(str(league_id), fixture)
        q = fixture["qualifier"]
        if not re.fullmatch(r"[1-9][0-9]{0,18}", q["revision"]):
            raise ValueError("revision は正の整数を表す文字列にしてください。")
        if q["submission_method"] not in {"external_leaderboard", "jbsl_qualifier_v1"}:
            raise ValueError("提出方式が不正です。")
        if not q["enabled"] and (q["starts_at"] is not None or q["ends_at"] is not None):
            raise ValueError("非 Qualifier の開始・終了は null にしてください。")
        start = parse_utc(q["starts_at"], nullable=True)
        end = parse_utc(q["ends_at"], nullable=True) or parse_utc(fixture["end"])
        if start is not None and start >= end:
            raise ValueError("実効終了日時は開始日時より後にしてください。")
        if q["enabled"] and not fixture["maps"]:
            raise ValueError("Qualifier を有効にするには譜面が必要です。")
        if entry["source"] not in {"sample", "live"}:
            raise ValueError("データ出所が不正です。")
        return merge_leaderboard(entry["upstream"], fixture, league_id)

    def save_league(self, league_id, fixture, expected_revision, *, preview=False):
        result = {}
        def update(state):
            old = state["leagues"].get(str(league_id))
            revision = old["fixture"]["qualifier"]["revision"] if old else None
            if revision != expected_revision:
                raise ApiProblem(409, "edit_conflict", "別の画面でリーグが更新されました。再読込してください。")
            original = old or self.drafts.get(league_id)
            if original is None:
                raise ApiProblem(409, "mock_fixture_missing", "先に実リーグを取り込んでください。")
            entry = copy.deepcopy(original)
            entry["fixture"] = copy.deepcopy(fixture)
            try:
                entry["fixture"]["qualifier"]["revision"] = str(int(revision or "0") + 1)
                merged = self.validate_entry(league_id, entry)
            except (ValueError, KeyError, TypeError, ApiProblem) as exc:
                raise ApiProblem(422, "invalid_settings", f"リーグ設定を保存できません: {exc}") from exc
            state["leagues"][str(league_id)] = entry
            result.update(entry=entry, merged=merged)
        if preview:
            with self.lock:
                update(copy.deepcopy(self.state))
        else:
            self.commit(update)
            self.log.add(role="admin", method="PUT", path=f"/admin/api/leagues/{league_id}", status=200, source="local")
        return result

    async def leaderboard(self, league_id):
        from .jbsl_web_proxy_server import merge_leaderboard
        state = self.current()
        entry = state["leagues"].get(str(league_id))
        if entry is None:
            return await self.public.get(f"/leaderboard/api/{league_id}", raw_response=True)
        if entry["source"] == "live" and state["behavior"]["upstream_mode"] == "live":
            board = await self.public.get(f"/leaderboard/api/{league_id}")
            fixture = copy.deepcopy(entry["fixture"])
            await self.beatsaver.fill(board, fixture, missing_only=True)
        else:
            board = entry["upstream"]
            fixture = entry["fixture"]
        return await self.scoresaber.fill(merge_leaderboard(board, fixture, league_id))

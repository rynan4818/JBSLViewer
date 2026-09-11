"""Persistent settings for the independently runnable debug score server."""
from __future__ import annotations
import copy
import json
import os
import threading
from collections import deque
from contextvars import ContextVar
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .config import Settings, utc_now
from .errors import ApiProblem
from .schemas import utc_text

request_id: ContextVar[str | None] = ContextVar("score_request_id", default=None)

class Behavior(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    upstream_base_url: str = "http://127.0.0.1:18080"
    upstream_timeout_seconds: int = Field(10, ge=1, le=120)
    compressed_replay_limit: int = Field(16777216, ge=1024, le=67108864)
    expanded_replay_limit: int = Field(134217728, ge=1024, le=536870912)
    metadata_limit: int = Field(524288, ge=1024, le=4194304)
    score_fault: Literal["none", "unavailable", "authentication_required", "rate_limited"] = "none"
    score_fault_route: Literal["all", "auth", "status", "reserve", "started", "result"] = "all"
    score_delay_ms: int = Field(0, ge=0, le=60000)
    stub_sid: str = Field("76561198000000000", min_length=1, max_length=128, pattern=r"^\S+$")
    stub_display_name: str = Field("JBSL Test Player", min_length=1, max_length=100)
    result_grace_seconds: int = Field(300, ge=0, le=604800)
    result_deadline_equal_is_accepted: bool = True
    challenge_timeout_seconds: int | None = Field(None, ge=1, le=604800)
    server_start_deadline_policy: Literal["effective_end_only", "effective_end_minus_song_duration"] = "effective_end_only"
    cache_fresh_seconds: int = Field(60, ge=0, le=3600)
    cache_stale_seconds: int = Field(300, ge=0, le=86400)
    session_seconds: int = Field(43200, ge=1, le=86400)
    rate_limit_enabled: bool = False
    clock_offset_seconds: int = Field(0, ge=-31536000, le=31536000)

    @model_validator(mode="after")
    def cache_order(self):
        url = urlsplit(self.upstream_base_url)
        if (url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password
                or url.query or url.fragment or url.path not in {"", "/"}):
            raise ValueError("接続先には認証情報やパスを含まない http(s)://host:port を指定してください。")
        try:
            port = url.port
        except ValueError as exc:
            raise ValueError("接続先ポートが不正です。") from exc
        if port == 0:
            raise ValueError("接続先ポートは1以上です。")
        if url.scheme == "http" and url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("HTTP接続はループバックに限ります。外部接続にはHTTPSを指定してください。")
        self.upstream_base_url = self.upstream_base_url.rstrip("/")
        if self.cache_stale_seconds < self.cache_fresh_seconds:
            raise ValueError("参考キャッシュ期限は通常キャッシュ期限以上にしてください。")
        return self


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


class SettingsView:
    def __init__(self, runtime): self.runtime = runtime
    def __getattr__(self, name): return getattr(self.runtime.score_settings(), name)


class Control:
    def __init__(self, data_dir: Path, *, score_port=18082, admin_port=18765):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "control.json"
        self.lock = threading.RLock()
        self.context = ContextVar("score_control_snapshot", default=None)
        self.log = TrafficLog()
        self.urls = {"score": f"http://127.0.0.1:{score_port}", "admin": f"http://127.0.0.1:{admin_port}"}
        self.base_settings = Settings(database_path=self.data_dir / "score.sqlite3", replay_dir=self.data_dir / "replays",
                                      allow_insecure_loopback_cookie=True)
        self.score_app = None
        if self.path.exists():
            self.state = json.loads(self.path.read_text(encoding="utf-8"))
            if self.state.get("schemaVersion") != 1:
                raise ValueError("Unknown control.json version")
            self.state["behavior"] = Behavior.model_validate(self.state["behavior"]).model_dump()
        else:
            self.state = {"schemaVersion": 1, "generation": 1, "behavior": Behavior().model_dump()}
            self._write(self.state)

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

    def score_settings(self):
        behavior = self.current()["behavior"]
        names = set(Behavior.model_fields) - {"score_fault", "score_fault_route", "score_delay_ms", "clock_offset_seconds"}
        offset = behavior["clock_offset_seconds"]
        return replace(self.base_settings, **{key: behavior[key] for key in names},
                       clock=lambda: utc_now() + timedelta(seconds=offset))

    def save_behavior(self, value: Behavior, expected: int):
        def update(state):
            if state["generation"] != expected:
                raise ApiProblem(409, "edit_conflict", "別の画面でサーバ設定が更新されました。再読込してください。")
            state["behavior"] = value.model_dump()
            state["generation"] += 1
        self.commit(update)
        self.log.add(role="admin", method="PUT", path="/admin/api/settings", status=200, source="local")


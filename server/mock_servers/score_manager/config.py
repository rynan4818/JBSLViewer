from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parent


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    upstream_timeout_seconds: int = 10
    upstream_base_url: str = "http://127.0.0.1:18080"
    database_path: Path = ROOT / "data" / "score_manager.sqlite3"
    replay_dir: Path = ROOT / "data" / "replays"
    auth_mode: str = "stub"
    stub_sid: str = "76561198000000000"
    stub_display_name: str = "JBSL Test Player"
    allow_insecure_loopback_cookie: bool = False
    session_seconds: int = 43_200
    cache_fresh_seconds: int = 60
    cache_stale_seconds: int = 300
    result_grace_seconds: int = 300
    result_deadline_equal_is_accepted: bool = True
    challenge_timeout_seconds: int | None = None
    server_start_deadline_policy: str = "effective_end_only"
    bsor_score_validation_profile: str = "basic_identity_only"
    compressed_replay_limit: int = 16 * 1024 * 1024
    expanded_replay_limit: int = 128 * 1024 * 1024
    metadata_limit: int = 512 * 1024
    rate_limit_enabled: bool = True
    steam_api_key: str | None = None
    steam_api_url: str | None = None
    oculus_api_url: str | None = None
    sqlite_busy_timeout_ms: int = 30_000
    clock: Callable[[], datetime] = field(default=utc_now, repr=False)

    @classmethod
    def from_env(cls) -> "Settings":
        timeout = os.getenv("JBSL_MOCK_CHALLENGE_TIMEOUT_SECONDS")
        return cls(
            upstream_base_url=os.getenv("JBSL_MOCK_UPSTREAM", "http://127.0.0.1:18080").rstrip("/"),
            database_path=Path(os.getenv("JBSL_MOCK_DB", str(ROOT / "data" / "score_manager.sqlite3"))),
            replay_dir=Path(os.getenv("JBSL_MOCK_REPLAY_DIR", str(ROOT / "data" / "replays"))),
            auth_mode=os.getenv("JBSL_MOCK_AUTH_MODE", "stub"),
            stub_sid=os.getenv("JBSL_MOCK_SID", "76561198000000000"),
            stub_display_name=os.getenv("JBSL_MOCK_DISPLAY_NAME", "JBSL Test Player"),
            allow_insecure_loopback_cookie=_env_bool("JBSL_MOCK_ALLOW_HTTP_LOOPBACK", False),
            result_grace_seconds=int(os.getenv("JBSL_MOCK_RESULT_GRACE_SECONDS", "300")),
            result_deadline_equal_is_accepted=_env_bool("JBSL_MOCK_DEADLINE_EQUAL_ACCEPTED", True),
            challenge_timeout_seconds=int(timeout) if timeout else None,
            server_start_deadline_policy=os.getenv("JBSL_MOCK_START_POLICY", "effective_end_only"),
            bsor_score_validation_profile=os.getenv("JBSL_MOCK_BSOR_SCORE_PROFILE", "basic_identity_only"),
            rate_limit_enabled=_env_bool("JBSL_MOCK_RATE_LIMIT", True),
            steam_api_key=os.getenv("JBSL_MOCK_STEAM_API_KEY"),
            steam_api_url=os.getenv("JBSL_MOCK_STEAM_API_URL"),
            oculus_api_url=os.getenv("JBSL_MOCK_OCULUS_API_URL"),
        )

    def validate(self) -> None:
        if self.auth_mode not in {"stub", "real-provider-test"}:
            raise ValueError("JBSL_MOCK_AUTH_MODE must be stub or real-provider-test")
        if self.result_grace_seconds < 0:
            raise ValueError("result grace must be non-negative")
        if self.server_start_deadline_policy not in {"effective_end_only", "effective_end_minus_song_duration"}:
            raise ValueError("invalid server start deadline policy")
        if self.bsor_score_validation_profile != "basic_identity_only":
            raise ValueError("only the undecided-safe basic_identity_only BSOR profile is implemented")


def require_loopback_bind(host: str) -> str:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("TEST ONLY servers may bind only to 127.0.0.1 or localhost")
    return host

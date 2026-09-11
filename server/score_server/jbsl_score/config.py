from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
REFUND_CONDITIONS = {
    "preflight_unstarted",
    "preflight_started",
    "quit",
    "restart",
    "unknown",
    "submission_disabled",
    "replay_unavailable",
    "abandoned",
}


@dataclass
class Policy:
    result_grace_seconds: int = 300
    reservations_enabled: bool = True
    start_deadline_policy: str = "effective_end"
    challenge_timeout_seconds: int = 0
    refund_conditions: list[str] = field(default_factory=list)
    max_active_per_user: int = 0
    cache_fresh_seconds: int = 60
    cache_stale_seconds: int = 300
    session_seconds: int = 43200
    max_sessions_per_user: int = 5
    auth_per_minute: int = 5
    status_per_minute: int = 60
    reserve_per_minute: int = 30
    result_per_minute: int = 30
    min_free_disk_mb: int = 512
    backup_interval_hours: int = 24
    backup_keep_count: int = 7

    @classmethod
    def parse(cls, raw):
        if not isinstance(raw, dict) or set(raw) != set(asdict(cls())):
            raise ValueError("全設定項目が必要です。未知の項目は指定できません。")
        bounds = {
            "result_grace_seconds": (0, 604800),
            "challenge_timeout_seconds": (0, 604800),
            "max_active_per_user": (0, 100),
            "cache_fresh_seconds": (0, 60),
            "cache_stale_seconds": (0, 300),
            "session_seconds": (300, 86400),
            "max_sessions_per_user": (1, 20),
            "auth_per_minute": (1, 600),
            "status_per_minute": (1, 600),
            "reserve_per_minute": (1, 600),
            "result_per_minute": (1, 600),
            "min_free_disk_mb": (64, 1048576),
            "backup_interval_hours": (0, 168),
            "backup_keep_count": (1, 100),
        }
        for name, (low, high) in bounds.items():
            if type(raw[name]) is not int or not low <= raw[name] <= high:
                raise ValueError(f"{name}: {low}～{high} の整数が必要です。")
        if type(raw["reservations_enabled"]) is not bool:
            raise ValueError("reservations_enabled: 真偽値が必要です。")
        if raw["start_deadline_policy"] not in ("effective_end", "end_minus_duration"):
            raise ValueError("開始締切方式が不正です。")
        conditions = raw["refund_conditions"]
        if not isinstance(conditions, list) or any(
            type(x) is not str or x not in REFUND_CONDITIONS for x in conditions
        ):
            raise ValueError("回数返却条件が不正です。")
        if len(set(conditions)) != len(conditions) or raw["cache_stale_seconds"] < raw["cache_fresh_seconds"]:
            raise ValueError("返却条件の重複、またはキャッシュ期限の逆転があります。")
        return cls(**raw)


@dataclass
class Config:
    data_dir: Path = ROOT / "data"
    api_host: str = "127.0.0.1"
    api_port: int = 18081
    api_public_url: str = "http://127.0.0.1:18081"
    admin_host: str = "127.0.0.1"
    admin_port: int = 18763
    admin_public_url: str = "http://127.0.0.1:18763"
    allow_http_loopback: bool = True
    jbsl_web_url: str = "https://jbsl-web.herokuapp.com"
    jbsl_web_token: str = field(default="", repr=False)
    steam_api_key: str = field(default="", repr=False)
    oculus_enabled: bool = True
    ssl_certfile: str = ""
    ssl_keyfile: str = ""
    trusted_proxy_ips: str = ""
    request_timeout_seconds: int = 60
    compressed_replay_limit: int = 16 * 1024 * 1024
    expanded_replay_limit: int = 64 * 1024 * 1024
    metadata_limit: int = 64 * 1024
    # Dependency injection is used in tests; there is deliberately no stub-auth switch.

    def validate(self):
        self.data_dir = Path(self.data_dir).resolve()
        for kind in ("api", "admin"):
            port = getattr(self, f"{kind}_port")
            if type(port) is not int or not 1024 <= port <= 65535:
                raise ValueError(f"{kind}_port must be an integer from 1024 to 65535")
            url = urlsplit(getattr(self, f"{kind}_public_url"))
            if (
                url.scheme not in ("https", "http")
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
                or url.path not in ("", "/")
            ):
                raise ValueError(f"{kind}_public_url must be an HTTP(S) origin without credentials or a path")
            host = getattr(self, f"{kind}_host")
            if url.scheme == "http" and not (
                self.allow_http_loopback and host in LOOPBACK and url.hostname in LOOPBACK
            ):
                raise ValueError("HTTP is allowed only with explicit loopback configuration")
        if self.api_port == self.admin_port:
            raise ValueError("API and admin must use separate ports")
        upstream = urlsplit(self.jbsl_web_url)
        if (
            not upstream.hostname
            or upstream.username
            or upstream.password
            or upstream.query
            or upstream.fragment
            or upstream.scheme not in ("http", "https")
        ):
            raise ValueError("jbsl_web_url is invalid")
        if upstream.scheme == "http" and upstream.hostname not in LOOPBACK:
            raise ValueError("jbsl-web must use HTTPS outside loopback")
        if bool(self.ssl_certfile) != bool(self.ssl_keyfile):
            raise ValueError("Both TLS certificate and key are required")
        if self.ssl_certfile and not (
            self.api_public_url.startswith("https://") and self.admin_public_url.startswith("https://")
        ):
            raise ValueError("Direct TLS requires HTTPS public URLs for both listeners")
        if (
            not self.ssl_certfile
            and not self.trusted_proxy_ips
            and any(url.startswith("https://") for url in (self.api_public_url, self.admin_public_url))
        ):
            raise ValueError("HTTPS requires direct TLS or explicitly trusted reverse proxy addresses")
        if type(self.request_timeout_seconds) is not int or not 5 <= self.request_timeout_seconds <= 300:
            raise ValueError("request_timeout_seconds must be between 5 and 300")
        if "*" in self.trusted_proxy_ips:
            raise ValueError("Explicit proxy addresses are required; wildcard is forbidden")
        return self

    @classmethod
    def load(cls, path=ROOT / "config.json"):
        path = Path(path).resolve()
        raw = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
        if not isinstance(raw, dict) or set(raw) - set(cls.__dataclass_fields__):
            raise ValueError("Unknown config.json settings")
        if "data_dir" in raw:
            raw["data_dir"] = path.parent / raw["data_dir"]
        for key in ("steam_api_key", "jbsl_web_token"):
            if f"JBSL_{key.upper()}" in os.environ:
                raw[key] = os.environ[f"JBSL_{key.upper()}"]
        return cls(**raw).validate()

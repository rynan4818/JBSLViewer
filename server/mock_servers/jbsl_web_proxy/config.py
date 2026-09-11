from __future__ import annotations
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent


def utc_now():
    return datetime.now(timezone.utc)


def normalize_public_url(value: str) -> str:
    message = "config.json public_url must be an HTTPS domain URL without a path, credentials, query, or custom port"
    if not isinstance(value, str):
        raise ValueError(message)
    value = value.strip()
    if not value:
        return ""
    try:
        url = urlsplit(value)
        host = url.hostname or ""
        if (url.scheme != "https" or url.path not in {"", "/"}
                or any(c.isspace() or c in "\\?#" for c in value)
                or url.username is not None or url.password is not None
                or url.port not in {None, 443} or url.netloc.endswith(":")
                or len(host) > 253 or "." not in host
                or not re.fullmatch(r"[a-z][a-z0-9-]*", host.rsplit(".", 1)[-1])
                or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split("."))):
            raise ValueError(message)
    except ValueError as exc:
        raise ValueError(message) from exc
    return "https://" + host


def load_public_url(path: Path | None = None) -> str:
    path = ROOT / "config.json" if path is None else Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return ""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError("config.json must contain valid JSON") from exc
    if not isinstance(data, dict) or set(data) - {"public_url"}:
        raise ValueError("config.json must be an object containing only public_url")
    return normalize_public_url(data.get("public_url", ""))


def prepare_http_scope(scope, public_url: str = "") -> bool:
    """Validate Host and use the configured HTTPS origin for public redirects."""
    authorities = [v for k, v in scope["headers"] if k.lower() == b"host"]
    if len(authorities) != 1:
        return False
    try:
        authority = authorities[0].decode("ascii")
        if any(c.isspace() or c in "\\?#" for c in authority):
            return False
        url = urlsplit("//" + authority)
        if url.username is not None or url.password is not None or url.path:
            return False
        port = url.port
        if url.hostname in {"127.0.0.1", "localhost", "testserver"}:
            return True
        if not public_url or url.hostname != urlsplit(public_url).hostname or port not in {None, 443}:
            return False
    except (ValueError, UnicodeError):
        return False
    # Never construct a browser URL from arbitrary forwarded headers or bind ports.
    host = urlsplit(public_url).netloc
    scope["scheme"] = "https"
    scope["server"] = (host, 443)
    scope["headers"] = [(k, v) for k, v in scope["headers"] if k.lower() != b"host"] + [(b"host", host.encode("ascii"))]
    return True


@dataclass(slots=True)
class Settings:
    fixture_path: Path = ROOT / "fixtures/qualifier_leagues.json"
    offline_upstream_dir: Path | None = ROOT / "fixtures/upstream"
    proxy_fault_profile: str = "none"
    public_url: str = ""

    @classmethod
    def from_env(cls):
        offline = os.getenv("JBSL_MOCK_OFFLINE_DIR")
        return cls(fixture_path=Path(os.getenv("JBSL_MOCK_FIXTURE", str(ROOT / "fixtures/qualifier_leagues.json"))),
                   offline_upstream_dir=Path(offline) if offline else None,
                   proxy_fault_profile=os.getenv("JBSL_MOCK_PROXY_FAULT", "none"),
                   public_url=load_public_url())

    def validate(self):
        self.public_url = normalize_public_url(self.public_url)
        if self.proxy_fault_profile not in {"none", "upstream_unavailable", "upstream_invalid"}:
            raise ValueError("invalid proxy fault profile")


def require_loopback_bind(host):
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("TEST ONLY servers may bind only to 127.0.0.1 or localhost")
    return host

"""Local administrator credentials and revocable browser sessions."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .errors import ApiProblem

COOKIE_NAME = "jbsl_relay_admin"
SESSION_SECONDS = 8 * 60 * 60
_DUMMY_HASH = "scrypt$16384$" + "00" * 16 + "$" + "00" * 32


def password_hash(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError("Password must contain 12 to 256 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
    return "scrypt$16384$" + salt.hex() + "$" + digest.hex()


def password_matches(password, encoded):
    try:
        algorithm, cost, salt, expected = encoded.split("$")
        if algorithm != "scrypt" or cost != "16384" or not isinstance(password, str) or len(password) > 256:
            return False
        salt, expected = bytes.fromhex(salt), bytes.fromhex(expected)
        if len(salt) != 16 or len(expected) != 32:
            return False
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError):
        return False


def token_hash(token):
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        return None
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def session_info(row):
    return {"username": row["username"], "csrfToken": row["csrf_token"],
            "expiresAt": datetime.fromtimestamp(row["expires_at"], timezone.utc).isoformat().replace("+00:00", "Z")}


class AdminAuth:
    def __init__(self, path: Path, *, clock=None):
        self.path = Path(path)
        self.clock = clock or time.time
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS admin_users (
                    username TEXT PRIMARY KEY, password_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS admin_sessions (
                    token_hash TEXT PRIMARY KEY, username TEXT NOT NULL,
                    csrf_token TEXT NOT NULL, expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_by_user ON admin_sessions(username, expires_at);
                CREATE TABLE IF NOT EXISTS login_attempts (
                    identity_hash TEXT PRIMARY KEY, window INTEGER NOT NULL, attempts INTEGER NOT NULL
                );
            """)

    @contextmanager
    def _db(self, *, write=False):
        with closing(sqlite3.connect(self.path, timeout=5, isolation_level=None)) as db:
            db.row_factory = sqlite3.Row
            if write:
                db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                if write:
                    db.commit()
            except BaseException:
                if write:
                    db.rollback()
                raise

    def has_admin(self):
        with self._db() as db:
            return db.execute("SELECT 1 FROM admin_users LIMIT 1").fetchone() is not None

    def set_admin(self, username, password, *, only_if_empty=False):
        if not isinstance(username, str) or not 1 <= len(username) <= 64 or username.strip() != username:
            raise ValueError("Admin username must contain 1 to 64 characters without surrounding spaces")
        encoded = password_hash(password)
        with self._db(write=True) as db:
            if only_if_empty and db.execute("SELECT 1 FROM admin_users LIMIT 1").fetchone():
                return False
            db.execute("INSERT INTO admin_users VALUES(?,?) ON CONFLICT(username) DO UPDATE SET "
                       "password_hash=excluded.password_hash", (username, encoded))
            db.execute("DELETE FROM admin_sessions WHERE username=?", (username,))
        return True

    def _limit_login(self, identity):
        now = int(self.clock() // 60)
        identity_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        with self._db(write=True) as db:
            db.execute("DELETE FROM login_attempts WHERE window<?", (now - 1,))
            db.execute("INSERT INTO login_attempts VALUES(?,?,1) ON CONFLICT(identity_hash) DO UPDATE SET "
                       "attempts=CASE WHEN window=excluded.window THEN attempts+1 ELSE 1 END, window=excluded.window",
                       (identity_hash, now))
            count = db.execute("SELECT attempts FROM login_attempts WHERE identity_hash=?", (identity_hash,)).fetchone()[0]
        if count > 5:
            raise ApiProblem(429, "rate_limited", "ログイン試行が多すぎます。1分ほど待ってから再試行してください。")

    def login(self, username, password, identity, old_token=None):
        self._limit_login(identity)
        valid_name = isinstance(username, str) and 1 <= len(username) <= 64 and username.strip() == username
        with self._db() as db:
            row = db.execute("SELECT password_hash FROM admin_users WHERE username=?", (username,)).fetchone() if valid_name else None
        encoded = row["password_hash"] if row else _DUMMY_HASH
        matches = password_matches(password, encoded)
        if not matches or row is None:
            raise ApiProblem(401, "invalid_login", "ユーザー名またはパスワードが違います。")
        token, csrf, now = secrets.token_urlsafe(32), secrets.token_urlsafe(32), self.clock()
        with self._db(write=True) as db:
            # A password reset racing this expensive verification must also revoke this login.
            current = db.execute("SELECT password_hash FROM admin_users WHERE username=?", (username,)).fetchone()
            if current is None or current["password_hash"] != encoded:
                raise ApiProblem(401, "invalid_login", "ユーザー名またはパスワードが違います。")
            db.execute("DELETE FROM admin_sessions WHERE expires_at<=? OR token_hash=?", (now, token_hash(old_token)))
            db.execute("INSERT INTO admin_sessions VALUES(?,?,?,?)", (token_hash(token), username, csrf, now + SESSION_SECONDS))
            db.execute("DELETE FROM admin_sessions WHERE username=? AND token_hash NOT IN "
                       "(SELECT token_hash FROM admin_sessions WHERE username=? ORDER BY expires_at DESC,rowid DESC LIMIT 5)",
                       (username, username))
        return token, session_info({"username": username, "csrf_token": csrf, "expires_at": now + SESSION_SECONDS})

    def authenticate(self, token, csrf=None, mutation=False):
        digest = token_hash(token)
        with self._db() as db:
            row = db.execute("SELECT username,csrf_token,expires_at FROM admin_sessions WHERE token_hash=? AND expires_at>?",
                             (digest, self.clock())).fetchone() if digest else None
        if row is None:
            raise ApiProblem(401, "admin_login_required", "管理者ログインが必要です。")
        if mutation and (not isinstance(csrf, str) or len(csrf) > 256
                         or not hmac.compare_digest(csrf.encode("utf-8"), row["csrf_token"].encode("utf-8"))):
            raise ApiProblem(403, "csrf_rejected", "画面を再読み込みしてから操作してください。")
        return session_info(row)

    def logout(self, token):
        with self._db(write=True) as db:
            db.execute("DELETE FROM admin_sessions WHERE token_hash=?", (token_hash(token),))

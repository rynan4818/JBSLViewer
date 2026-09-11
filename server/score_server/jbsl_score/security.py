from __future__ import annotations

import hashlib
import hmac
import secrets

from .database import token_hash
from .errors import ApiProblem
from .service import timestamp
from .timing import measure_operation


def password_hash(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError("Password must contain 12 to 256 characters")
    salt = secrets.token_bytes(16)
    value = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
    return "scrypt$16384$" + salt.hex() + "$" + value.hex()


def password_matches(password, encoded):
    try:
        algorithm, cost, salt, expected = encoded.split("$")
        if algorithm != "scrypt" or cost != "16384" or not isinstance(password, str) or len(password) > 256:
            return False
        actual = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32)
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


DUMMY_HASH = "scrypt$16384$" + "00" * 16 + "$" + "00" * 32


class Security:
    def __init__(self, service):
        self.service, self.db = service, service.db

    @measure_operation()
    def create_admin(self, username, password):
        if not isinstance(username, str) or not 1 <= len(username) <= 64 or username.strip() != username:
            raise ValueError("Invalid admin username")
        encoded = password_hash(password)
        with self.db.transaction() as c:
            c.execute(
                "INSERT INTO admin_users VALUES(?,?,?) ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash",
                (username, encoded, self.service.clock()),
            )
            c.execute("DELETE FROM admin_sessions WHERE username=?", (username,))
            self.db.audit(
                self.service.clock(), "local-cli", "admin_password_set", details={"username": username}, connection=c
            )

    @measure_operation()
    def login_player(self, ticket, provider, old_token=None):
        identity = self.service.verifier.verify(ticket, provider)
        policy, _ = self.db.policy()
        now, token = self.service.clock(), secrets.token_urlsafe(32)
        with self.db.transaction() as c:
            display_name = self.service.resolve_player_name(c, identity.sid, identity.display_name)
            c.execute(
                "INSERT INTO users VALUES(?,?,?,?) ON CONFLICT(sid) DO UPDATE SET "
                "display_name=excluded.display_name,updated_at=excluded.updated_at",
                (identity.sid, display_name, now, now),
            )
            if old_token:
                c.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(old_token),))
            c.execute(
                "INSERT INTO sessions VALUES(?,?,?,?,?)",
                (token_hash(token), identity.sid, provider, now, now + policy.session_seconds),
            )
            # Keep the just-created token, even when several logins have the same timestamp.
            c.execute(
                "DELETE FROM sessions WHERE sid=? AND token_hash<>? AND token_hash NOT IN "
                "(SELECT token_hash FROM sessions WHERE sid=? AND token_hash<>? ORDER BY created_at DESC,token_hash LIMIT ?)",
                (identity.sid, token_hash(token), identity.sid, token_hash(token), policy.max_sessions_per_user - 1),
            )
            self.db.audit(now, identity.sid, "authentication_succeeded", details={"provider": provider}, connection=c)
        return token, {
            "schemaVersion": 1,
            "authenticated": True,
            "user": {"sid": identity.sid, "displayName": display_name},
            "expiresAt": timestamp(now + policy.session_seconds),
        }

    def player(self, token):
        if not token or len(token) > 256:
            raise ApiProblem(401, "authentication_required", "An authenticated session is required.")
        with self.db.read() as c:
            row = c.execute(
                "SELECT s.*,u.display_name FROM sessions s JOIN users u ON u.sid=s.sid WHERE token_hash=? AND expires_at>?",
                (token_hash(token), self.service.clock()),
            ).fetchone()
        if row is None:
            raise ApiProblem(401, "authentication_required", "An authenticated session is required.")
        return dict(row)

    @measure_operation()
    def login_admin(self, username, password, old_token=None):
        if not isinstance(username, str) or not 1 <= len(username) <= 64:
            raise ApiProblem(401, "invalid_login", "ユーザー名またはパスワードが違います。")
        with self.db.read() as c:
            row = c.execute("SELECT * FROM admin_users WHERE username=?", (username,)).fetchone()
        valid = password_matches(password, row["password_hash"] if row else DUMMY_HASH)
        if not valid or row is None:
            self.db.audit(self.service.clock(), "anonymous", "admin_login_failed")
            raise ApiProblem(401, "invalid_login", "ユーザー名またはパスワードが違います。")
        token, csrf, now = secrets.token_urlsafe(32), secrets.token_urlsafe(32), self.service.clock()
        with self.db.transaction() as c:
            if old_token:
                c.execute("DELETE FROM admin_sessions WHERE token_hash=?", (token_hash(old_token),))
            c.execute("INSERT INTO admin_sessions VALUES(?,?,?,?)", (token_hash(token), username, csrf, now + 28800))
            c.execute(
                "DELETE FROM admin_sessions WHERE username=? AND token_hash NOT IN "
                "(SELECT token_hash FROM admin_sessions WHERE username=? ORDER BY expires_at DESC,rowid DESC LIMIT 5)",
                (username, username),
            )
            self.db.audit(now, "admin:" + username, "admin_login_succeeded", connection=c)
        return token, {"username": username, "csrfToken": csrf, "expiresAt": timestamp(now + 28800)}

    def admin(self, token, csrf=None, mutation=False):
        if not token or len(token) > 256:
            raise ApiProblem(401, "admin_login_required", "管理者ログインが必要です。")
        with self.db.read() as c:
            row = c.execute(
                "SELECT * FROM admin_sessions WHERE token_hash=? AND expires_at>?",
                (token_hash(token), self.service.clock()),
            ).fetchone()
        if row is None:
            raise ApiProblem(401, "admin_login_required", "管理者ログインが必要です。")
        if mutation and (not isinstance(csrf, str) or not hmac.compare_digest(csrf, row["csrf_token"])):
            raise ApiProblem(403, "csrf_rejected", "画面を再読み込みしてから操作してください。")
        return dict(row)

    @measure_operation()
    def create_service_token(self, name):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 64:
            raise ValueError("Token name must contain 1 to 64 characters")
        token = "jbsl_" + secrets.token_urlsafe(32)
        with self.db.transaction() as c:
            c.execute(
                "INSERT INTO service_tokens VALUES(?,?,?,NULL) ON CONFLICT(name) DO UPDATE SET "
                "token_hash=excluded.token_hash,created_at=excluded.created_at,revoked_at=NULL",
                (token_hash(token), name, self.service.clock()),
            )
            self.db.audit(
                self.service.clock(), "local-cli", "service_token_rotated", details={"name": name}, connection=c
            )
        return token

    def service_token(self, authorization):
        if not isinstance(authorization, str) or not authorization.startswith("Bearer ") or len(authorization) > 256:
            raise ApiProblem(401, "service_authentication_required", "A service bearer token is required.")
        with self.db.read() as c:
            row = c.execute(
                "SELECT name FROM service_tokens WHERE token_hash=? AND revoked_at IS NULL",
                (token_hash(authorization[7:]),),
            ).fetchone()
        if row is None:
            raise ApiProblem(401, "service_authentication_required", "A service bearer token is required.")
        return row["name"]

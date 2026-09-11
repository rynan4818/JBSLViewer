from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict

from .config import Policy
from .timing import current_operation, elapsed_ms


REPLAY_VIEWER_SCHEMA = """
CREATE TABLE replay_viewer_tokens (
 token_hash TEXT PRIMARY KEY,
 result_id TEXT NOT NULL REFERENCES results(id) ON DELETE CASCADE,
 admin_session_hash TEXT NOT NULL REFERENCES admin_sessions(token_hash) ON DELETE CASCADE,
 viewer TEXT NOT NULL CHECK(viewer IN ('beatleader','arcviewer')),
 created_at REAL NOT NULL, expires_at REAL NOT NULL
);
CREATE INDEX replay_viewer_expiry ON replay_viewer_tokens(expires_at);
CREATE INDEX replay_viewer_session ON replay_viewer_tokens(admin_session_hash);
CREATE INDEX replay_viewer_result ON replay_viewer_tokens(result_id);
"""

SCHEMA = """
CREATE TABLE users (
 sid TEXT PRIMARY KEY, display_name TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE sessions (
 token_hash TEXT PRIMARY KEY, sid TEXT NOT NULL REFERENCES users(sid), provider TEXT NOT NULL,
 created_at REAL NOT NULL, expires_at REAL NOT NULL
);
CREATE INDEX sessions_user ON sessions(sid, created_at);
CREATE TABLE admin_users (
 username TEXT PRIMARY KEY, password_hash TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE admin_sessions (
 token_hash TEXT PRIMARY KEY, username TEXT NOT NULL REFERENCES admin_users(username),
 csrf_token TEXT NOT NULL, expires_at REAL NOT NULL
);
CREATE TABLE service_tokens (
 token_hash TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at REAL NOT NULL, revoked_at REAL
);
CREATE TABLE policy (
 id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, value_json TEXT NOT NULL
);
CREATE TABLE league_cache (
 league_id INTEGER PRIMARY KEY, projection_json TEXT NOT NULL, fetched_at REAL NOT NULL, last_error TEXT
);
CREATE TABLE budgets (
 sid TEXT NOT NULL REFERENCES users(sid), league_id INTEGER NOT NULL, map_hash TEXT NOT NULL,
 characteristic TEXT NOT NULL, difficulty TEXT NOT NULL, used INTEGER NOT NULL CHECK(used>=0),
 total INTEGER NOT NULL CHECK(total>=used), last_limit INTEGER NOT NULL,
 PRIMARY KEY(sid,league_id,map_hash,characteristic,difficulty)
);
CREATE TABLE reservation_requests (
 sid TEXT NOT NULL REFERENCES users(sid), key TEXT NOT NULL, digest TEXT NOT NULL,
 created_at REAL NOT NULL, PRIMARY KEY(sid,key)
);
CREATE TABLE challenges (
 id TEXT PRIMARY KEY, sid TEXT NOT NULL REFERENCES users(sid), league_id INTEGER NOT NULL,
 map_hash TEXT NOT NULL, characteristic TEXT NOT NULL, difficulty TEXT NOT NULL,
 revision TEXT NOT NULL, reserve_key TEXT NOT NULL, request_digest TEXT NOT NULL,
 response_json TEXT NOT NULL, attempt_number INTEGER NOT NULL, attempt_limit INTEGER NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('reserved','started','submitted','abandoned')),
 reserved_at REAL NOT NULL, received_at REAL NOT NULL, started_at REAL, submitted_at REAL,
 effective_end REAL NOT NULL, accept_until REAL NOT NULL, timeout_at REAL, abandoned_reason TEXT,
 policy_json TEXT NOT NULL, policy_revision INTEGER NOT NULL, provider TEXT NOT NULL,
 refunded INTEGER NOT NULL DEFAULT 0 CHECK(refunded IN (0,1)), refund_reason TEXT,
 started_json TEXT, client_version TEXT NOT NULL, game_version TEXT NOT NULL,
 UNIQUE(sid,reserve_key)
);
CREATE INDEX challenges_user ON challenges(sid,league_id,reserved_at);
CREATE INDEX challenges_expiry ON challenges(status,accept_until);
CREATE TABLE results (
 id TEXT PRIMARY KEY, challenge_id TEXT NOT NULL UNIQUE REFERENCES challenges(id),
 client_key TEXT NOT NULL UNIQUE, digest TEXT NOT NULL, metadata_json TEXT NOT NULL,
 response_json TEXT NOT NULL, received_at REAL NOT NULL, end_type TEXT NOT NULL,
 valid_for_ranking INTEGER NOT NULL CHECK(valid_for_ranking IN (0,1)), invalid_reason TEXT,
 modified_score INTEGER, max_score INTEGER, replay_sha256 TEXT,
 canceled INTEGER NOT NULL DEFAULT 0 CHECK(canceled IN (0,1)), moderation_version INTEGER NOT NULL DEFAULT 0,
 moderation_reason TEXT, moderated_at REAL,
 CHECK(valid_for_ranking=0 OR (replay_sha256 IS NOT NULL AND modified_score IS NOT NULL)),
 CHECK(end_type IN ('clear','fail') OR valid_for_ranking=0)
);
CREATE INDEX results_recent ON results(received_at);
CREATE TABLE replay_blobs (
 result_id TEXT PRIMARY KEY REFERENCES results(id), gzip_data BLOB NOT NULL, raw_size INTEGER NOT NULL
);
CREATE TABLE changes (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, league_id INTEGER NOT NULL, result_id TEXT NOT NULL REFERENCES results(id),
 event TEXT NOT NULL, occurred_at REAL NOT NULL, payload_json TEXT NOT NULL
);
CREATE INDEX changes_league ON changes(league_id,seq);
CREATE TABLE audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at REAL NOT NULL, actor TEXT NOT NULL,
 event TEXT NOT NULL, challenge_id TEXT, request_id TEXT, details_json TEXT NOT NULL
);
CREATE INDEX audit_challenge ON audit(challenge_id,id);
CREATE TABLE rate_limits (
 bucket TEXT NOT NULL, identity TEXT NOT NULL, window INTEGER NOT NULL, count INTEGER NOT NULL,
 PRIMARY KEY(bucket,identity)
);
CREATE TABLE maintenance (
 name TEXT PRIMARY KEY, value TEXT NOT NULL
);
""" + REPLAY_VIEWER_SCHEMA + "PRAGMA user_version=3;"


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Database:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.read() as c:
            c.execute("PRAGMA journal_mode=WAL")
            version = c.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                c.executescript("BEGIN IMMEDIATE;" + SCHEMA)
                c.execute("INSERT INTO policy VALUES(1,1,?)", (dumps(asdict(Policy())),))
                c.commit()
            elif version in (1, 2):
                migration = "BEGIN IMMEDIATE;"
                if version == 1:
                    migration += """
                    CREATE TABLE reservation_requests (
                      sid TEXT NOT NULL REFERENCES users(sid), key TEXT NOT NULL, digest TEXT NOT NULL,
                      created_at REAL NOT NULL, PRIMARY KEY(sid,key));
                    INSERT INTO reservation_requests SELECT sid,reserve_key,request_digest,received_at FROM challenges;
                    """
                c.executescript(migration + REPLAY_VIEWER_SCHEMA + "PRAGMA user_version=3; COMMIT;")
            elif version != 3:
                raise RuntimeError("Unsupported database schema; use the matching server version")

    @contextmanager
    def read(self):
        c = sqlite3.connect(self.path, timeout=20, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=20000")
        c.execute("PRAGMA synchronous=FULL")
        try:
            yield c
        finally:
            if c.in_transaction:
                c.rollback()
            c.close()

    @contextmanager
    def transaction(self):
        with self.read() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
                c.commit()
            except BaseException:
                c.rollback()
                raise

    def policy(self):
        with self.read() as c:
            row = c.execute("SELECT * FROM policy WHERE id=1").fetchone()
        return Policy.parse(json.loads(row["value_json"])), row["revision"]

    def audit(self, now, actor, event, challenge_id=None, request_id=None, details=None, connection=None):
        operation = current_operation.get()
        if request_id is None and operation is not None:
            request_id = operation.request_id
        details = {**(details or {}), "elapsedMs": elapsed_ms()}
        args = (now, actor, event, challenge_id, request_id, dumps(details))
        sql = "INSERT INTO audit(occurred_at,actor,event,challenge_id,request_id,details_json) VALUES(?,?,?,?,?,?)"
        if connection is not None:
            connection.execute(sql, args)
        else:
            with self.transaction() as c:
                c.execute(sql, args)

    def rate_limit(self, bucket, identity, limit, now):
        from .errors import ApiProblem

        window = int(now // 60)
        with self.transaction() as c:
            c.execute(
                "INSERT INTO rate_limits VALUES(?,?,?,1) ON CONFLICT(bucket,identity) DO UPDATE SET "
                "window=excluded.window,count=CASE WHEN rate_limits.window=excluded.window "
                "THEN rate_limits.count+1 ELSE 1 END",
                (bucket, token_hash(identity), window),
            )
            count = c.execute(
                "SELECT count FROM rate_limits WHERE bucket=? AND identity=?", (bucket, token_hash(identity))
            ).fetchone()[0]
        if count > limit:
            raise ApiProblem(429, "rate_limited", "Rate limit exceeded.")

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, sid TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  id_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  auth_provider TEXT NOT NULL, created_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
  expires_at TEXT NOT NULL, revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS league_qualifier_caches (
  league_id INTEGER PRIMARY KEY, qualifier_revision TEXT NOT NULL,
  projection_json TEXT NOT NULL, fetched_at TEXT NOT NULL, last_error TEXT, source_url TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS attempt_budgets (
  user_id TEXT NOT NULL REFERENCES users(id), league_id INTEGER NOT NULL,
  map_hash TEXT NOT NULL, characteristic TEXT NOT NULL, difficulty TEXT NOT NULL,
  attempt_limit INTEGER NOT NULL CHECK(attempt_limit BETWEEN 1 AND 100),
  used_attempts INTEGER NOT NULL CHECK(used_attempts >= 0), version INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(user_id, league_id, map_hash, characteristic, difficulty)
);
CREATE TABLE IF NOT EXISTS reservation_requests (
  user_id TEXT NOT NULL REFERENCES users(id), idempotency_key TEXT NOT NULL,
  request_digest TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','succeeded')),
  challenge_id TEXT UNIQUE, response_json TEXT, created_at TEXT NOT NULL, succeeded_at TEXT,
  PRIMARY KEY(user_id, idempotency_key),
  CHECK((state='pending' AND challenge_id IS NULL AND response_json IS NULL AND succeeded_at IS NULL)
     OR (state='succeeded' AND challenge_id IS NOT NULL AND response_json IS NOT NULL AND succeeded_at IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS challenges (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), league_id INTEGER NOT NULL,
  map_hash TEXT NOT NULL, characteristic TEXT NOT NULL, difficulty TEXT NOT NULL,
  qualifier_revision TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_digest TEXT NOT NULL,
  attempt_number INTEGER NOT NULL, attempt_limit_at_reserve INTEGER NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('reserved','started','submitted','abandoned')),
  reserve_received_at TEXT NOT NULL, reserved_at TEXT NOT NULL, started_at TEXT, submitted_at TEXT,
  qualifier_end_at TEXT NOT NULL, result_accept_until TEXT NOT NULL,
  client_version TEXT NOT NULL, game_version TEXT NOT NULL,
  started_request_json TEXT,
  UNIQUE(user_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS results (
  id TEXT PRIMARY KEY, challenge_id TEXT NOT NULL UNIQUE REFERENCES challenges(id),
  client_result_id TEXT NOT NULL UNIQUE, metadata_json TEXT NOT NULL, response_json TEXT NOT NULL,
  end_state TEXT NOT NULL, end_action TEXT NOT NULL, end_type TEXT NOT NULL,
  multiplied_score INTEGER, modified_score INTEGER, max_possible_modified_score INTEGER,
  missed_count INTEGER, bad_cuts_count INTEGER, good_cuts_count INTEGER, max_combo INTEGER,
  full_combo INTEGER, energy REAL, modifiers_json TEXT,
  submission_allowed_at_start INTEGER NOT NULL, remained_allowed INTEGER NOT NULL,
  valid_for_ranking INTEGER NOT NULL, invalid_reason TEXT,
  restart_detected INTEGER NOT NULL, play_instance_count INTEGER NOT NULL,
  replay_sha256 TEXT, replay_size INTEGER, received_at TEXT NOT NULL,
  CHECK(end_type IN ('clear','fail','quit','restart','unknown','preflight_rejected')),
  CHECK(end_type NOT IN ('quit','restart','unknown','preflight_rejected') OR valid_for_ranking=0),
  CHECK((replay_sha256 IS NULL) = (replay_size IS NULL)),
  CHECK(valid_for_ranking=0 OR replay_sha256 IS NOT NULL)
);
CREATE TABLE IF NOT EXISTS replay_blobs (
  result_id TEXT PRIMARY KEY REFERENCES results(id), storage_path TEXT NOT NULL UNIQUE,
  byte_count INTEGER NOT NULL, sha256 TEXT NOT NULL, stored_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at TEXT NOT NULL,
  user_id TEXT, challenge_id TEXT, event_type TEXT NOT NULL, details_json TEXT NOT NULL
);
"""


def session_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


class Database:
    def __init__(self, path: Path, busy_timeout_ms: int = 30_000):
        self.path = Path(path)
        self.busy_timeout_ms = busy_timeout_ms
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            if "source_url" not in {row[1] for row in connection.execute("PRAGMA table_info(league_qualifier_caches)")}:
                connection.execute("ALTER TABLE league_qualifier_caches ADD COLUMN source_url TEXT NOT NULL DEFAULT ''")
            connection.execute("PRAGMA journal_mode=WAL")

    def connect(self) -> sqlite3.Connection:
        # Connections used by result uploads can be acquired/released by different
        # worker-pool threads while one request owns them exclusively.
        connection = sqlite3.connect(self.path, timeout=self.busy_timeout_ms / 1000, isolation_level=None, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        return connection

    def health(self) -> bool:
        with self.connect() as connection:
            return connection.execute("SELECT 1").fetchone()[0] == 1

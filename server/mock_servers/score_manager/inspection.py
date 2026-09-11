"""Read-only, paginated views of the actual score database (no synthetic results)."""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from .errors import ApiProblem
from .schemas import parse_utc, utc_text


class Inspector:
    def __init__(self, control):
        self.control = control

    @contextmanager
    def connection(self):
        settings = self.control.score_settings()
        now = settings.clock()

        def effective_status(status, deadline, reserved_at):
            expired = now > parse_utc(deadline) if settings.result_deadline_equal_is_accepted else now >= parse_utc(deadline)
            if settings.challenge_timeout_seconds is not None:
                expired = expired or now >= parse_utc(reserved_at) + timedelta(seconds=settings.challenge_timeout_seconds)
            return "abandoned" if status in {"reserved", "started"} and expired else status

        db = self.control.score_app.state.db.connect()
        db.create_function("effective_status", 3, effective_status, deterministic=True)
        try:
            # A single read transaction keeps counts and page contents consistent.
            db.execute("BEGIN")
            yield db
        finally:
            db.rollback()
            db.close()

    @staticmethod
    def filters(league_id=None, sid="", q="", **_):
        clauses, params = [], []
        if league_id is not None:
            clauses.append("c.league_id=?")
            params.append(league_id)
        if sid:
            clauses.append("u.sid=?")
            params.append(sid)
        if q:
            literal = q.replace("!", "!!").replace("%", "!%").replace("_", "!_")
            clauses.append("(c.id LIKE ? ESCAPE '!' OR c.map_hash LIKE ? ESCAPE '!')")
            params.extend([f"%{literal}%"] * 2)
        return clauses, params

    @staticmethod
    def page(db, select, source, clauses, params, order, page=1, page_size=25):
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        total = db.execute("SELECT COUNT(*) " + source + where, params).fetchone()[0]
        rows = db.execute(select + source + where + " ORDER BY " + order + " LIMIT ? OFFSET ?",
                          [*params, page_size, (page - 1) * page_size]).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": page, "pageSize": page_size}

    def state(self):
        with self.connection() as db:
            counts = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("users", "challenges", "results", "league_qualifier_caches")}
            statuses = {name: 0 for name in ("reserved", "started", "submitted", "abandoned")}
            statuses.update({row[0]: row[1] for row in db.execute(
                "SELECT effective_status(status,result_accept_until,reserved_at),COUNT(*) FROM challenges GROUP BY 1")})
            ranked = db.execute("SELECT COUNT(*) FROM results WHERE valid_for_ranking=1").fetchone()[0]
        return {"counts": counts, "challengeCounts": statuses, "rankedResults": ranked,
                "unrankedResults": counts["results"] - ranked,
                "serverTime": utc_text(self.control.score_settings().clock())}

    def challenges(self, *, status="all", page=1, page_size=25, **filters):
        clauses, params = self.filters(**filters)
        if status != "all":
            clauses.append("effective_status(c.status,c.result_accept_until,c.reserved_at)=?")
            params.append(status)
        with self.connection() as db:
            return self.page(db,
                "SELECT c.*,u.sid,u.display_name,effective_status(c.status,c.result_accept_until,c.reserved_at) AS effective_status,"
                "r.id AS result_id,r.valid_for_ranking,r.invalid_reason,r.end_type ",
                "FROM challenges c JOIN users u ON u.id=c.user_id LEFT JOIN results r ON r.challenge_id=c.id",
                clauses, params, "c.reserved_at DESC,c.id DESC", page, page_size)

    def results(self, *, ranking="all", end_type="all", page=1, page_size=25, **filters):
        clauses, params = self.filters(**filters)
        if ranking != "all":
            clauses.append("r.valid_for_ranking=?")
            params.append(int(ranking == "valid"))
        if end_type != "all":
            clauses.append("r.end_type=?")
            params.append(end_type)
        with self.connection() as db:
            return self.page(db,
                "SELECT r.id,r.challenge_id,r.received_at,r.end_type,r.valid_for_ranking,r.invalid_reason,"
                "r.modified_score,r.multiplied_score,r.max_possible_modified_score,r.replay_size,"
                "c.league_id,c.map_hash,c.characteristic,c.difficulty,c.attempt_number,u.sid,u.display_name ",
                "FROM results r JOIN challenges c ON c.id=r.challenge_id JOIN users u ON u.id=c.user_id",
                clauses, params, "r.received_at DESC,r.id DESC", page, page_size)

    @staticmethod
    def decode_result(row):
        result = dict(row)
        for column, name in (("metadata_json", "metadata"), ("response_json", "response"), ("modifiers_json", "modifiers")):
            raw = result.pop(column)
            result[name] = json.loads(raw) if raw is not None else None
        return result

    def challenge(self, challenge_id):
        with self.connection() as db:
            row = db.execute(
                "SELECT c.*,u.sid,u.display_name,effective_status(c.status,c.result_accept_until,c.reserved_at) AS effective_status "
                "FROM challenges c JOIN users u ON u.id=c.user_id WHERE c.id=?", (challenge_id,)).fetchone()
            if row is None:
                raise ApiProblem(404, "challenge_not_found", "Challenge が見つかりません。")
            challenge = dict(row)
            timeout = self.control.score_settings().challenge_timeout_seconds
            challenge["operationalTimeoutAt"] = utc_text(parse_utc(challenge["reserved_at"]) + timedelta(seconds=timeout)) if timeout else None
            started = challenge.pop("started_request_json")
            challenge["startedRequest"] = json.loads(started) if started else None
            result_row = db.execute("SELECT * FROM results WHERE challenge_id=?", (challenge_id,)).fetchone()
            result = self.decode_result(result_row) if result_row else None
            replay = None
            if result:
                blob = db.execute("SELECT * FROM replay_blobs WHERE result_id=?", (result["id"],)).fetchone()
                if blob:
                    saved_path = Path(blob["storage_path"]).resolve()
                    replay_root = self.control.base_settings.replay_dir.resolve()
                    exists = saved_path.is_relative_to(replay_root) and saved_path.is_file()
                    replay = {"sha256": blob["sha256"], "byteCount": blob["byte_count"],
                              "storedAt": blob["stored_at"], "fileExists": exists}
            events = []
            for row in db.execute("SELECT id,occurred_at,event_type,details_json FROM audit_events WHERE challenge_id=? ORDER BY id", (challenge_id,)):
                item = dict(row)
                item["details"] = json.loads(item.pop("details_json"))
                events.append(item)
        return {"challenge": challenge, "result": result, "replay": replay, "events": events,
                "serverTime": utc_text(self.control.score_settings().clock())}

    def result(self, result_id):
        with self.connection() as db:
            row = db.execute("SELECT challenge_id FROM results WHERE id=?", (result_id,)).fetchone()
        if row is None:
            raise ApiProblem(404, "result_not_found", "提出スコアが見つかりません。")
        return self.challenge(row["challenge_id"])

    def budgets(self, *, league_id=None, sid="", page=1, page_size=25):
        clauses, params = [], []
        for name, value in (("b.league_id", league_id), ("u.sid", sid or None)):
            if value is not None:
                clauses.append(name + "=?")
                params.append(value)
        with self.connection() as db:
            return self.page(db, "SELECT u.sid,b.league_id,b.map_hash,b.characteristic,b.difficulty,b.used_attempts,b.attempt_limit ",
                "FROM attempt_budgets b JOIN users u ON u.id=b.user_id", clauses, params,
                "b.league_id,u.sid,b.map_hash,b.characteristic,b.difficulty", page, page_size)

    def audit(self, *, page=1, page_size=25):
        with self.connection() as db:
            result = self.page(db, "SELECT a.id,a.occurred_at,a.challenge_id,a.event_type,a.details_json,u.sid ",
                "FROM audit_events a LEFT JOIN users u ON u.id=a.user_id", [], [], "a.id DESC", page, page_size)
        for row in result["items"]:
            row["details"] = json.loads(row.pop("details_json"))
        return result

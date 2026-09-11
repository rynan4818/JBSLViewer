from __future__ import annotations

import json
import logging
import os
import secrets
import sqlite3
import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from starlette.datastructures import UploadFile

from .auth import real_provider, stub
from .bsor_reader import DecodedReplay, decode_gzip
from .config import Settings, require_loopback_bind
from .database import Database, session_hash
from .errors import ApiProblem, problem_response
from .jbsl_client import LeaderboardClient
from .schemas import canonical_digest, normalize_map, parse_utc, require_positive_int, require_uuid, utc_text


LOG = logging.getLogger("jbsl_mock.score")
STATUS_REASONS = (
    "league_not_found", "qualifier_disabled", "wrong_submission_method", "league_not_open",
    "outside_qualifier_window", "map_not_found", "not_participant",
)


class RateLimiter:
    LIMITS = {"authSession": 5, "authMe": 30, "status": 30, "reserve": 10, "started": 20, "result": 10}

    def __init__(self, enabled: bool):
        self.enabled = enabled
        self.events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self.lock = threading.Lock()

    def check(self, route: str, identity: str, now: datetime, *, enabled: bool | None = None) -> None:
        if not (self.enabled if enabled is None else enabled) or route not in self.LIMITS:
            return
        timestamp = now.timestamp()
        key = (route, identity)
        with self.lock:
            events = self.events[key]
            while events and events[0] <= timestamp - 60:
                events.popleft()
            if len(events) >= self.LIMITS[route]:
                raise ApiProblem(429, "rate_limited", "Rate limit exceeded.")
            events.append(timestamp)


def _json_response(body: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status)


def _request_identity(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _get_session(db: Database, token: str | None, now: datetime) -> sqlite3.Row:
    if not token:
        raise ApiProblem(401, "authentication_required", "An authenticated session is required.")
    with db.connect() as connection:
        row = connection.execute(
            "SELECT s.*,u.sid,u.display_name FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.id_hash=?",
            (session_hash(token),),
        ).fetchone()
        if row is None or row["revoked_at"] is not None or parse_utc(row["expires_at"]) <= now:
            raise ApiProblem(401, "authentication_required", "An authenticated session is required.")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE sessions SET last_seen_at=? WHERE id_hash=?", (utc_text(now), row["id_hash"]))
        connection.commit()
        return row


def _find_map(projection: dict[str, Any], map_key: dict[str, str]) -> dict[str, Any] | None:
    return next((m for m in projection["maps"] if all(m[k] == map_key[k] for k in map_key)), None)


def _effective_end(projection: dict[str, Any]) -> datetime:
    return parse_utc(projection["qualifier"]["ends_at"], nullable=True) or parse_utc(projection["end"])


def _eligibility(projection: dict[str, Any], map_key: dict[str, str], sid: str, now: datetime, settings: Settings) -> tuple[str, dict[str, Any] | None, bool]:
    qualifier = projection["qualifier"]
    found_map = _find_map(projection, map_key)
    participant = any(p["sid"] == sid for p in projection["participants"])
    if not qualifier["enabled"]:
        return "qualifier_disabled", found_map, participant
    if qualifier["submission_method"] != "jbsl_qualifier_v1":
        return "wrong_submission_method", found_map, participant
    if not projection["isLive"] or not projection["isOpen"]:
        return "league_not_open", found_map, participant
    start = parse_utc(qualifier["starts_at"], nullable=True)
    end = _effective_end(projection)
    deadline = end
    if settings.server_start_deadline_policy == "effective_end_minus_song_duration" and found_map and found_map["song_duration_seconds"] is not None:
        deadline -= timedelta(seconds=found_map["song_duration_seconds"])
    if (start is not None and now < start) or now > deadline:
        return "outside_qualifier_window", found_map, participant
    if found_map is None:
        return "map_not_found", None, participant
    if not participant:
        return "not_participant", found_map, False
    return "eligible", found_map, True


def _league_body(projection: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": projection["league_id"], "name": projection["league_title"],
        "submissionMethod": projection["qualifier"]["submission_method"],
        "revision": projection["qualifier"]["revision"],
    }


def _map_body(found: dict[str, Any], attempt_limit: int | None = None) -> dict[str, Any]:
    return {
        "hash": found["hash"], "characteristic": found["characteristic"], "difficulty": found["difficulty"],
        "title": found.get("title"), "attemptLimit": found["qualifier_attempt_limit"] if attempt_limit is None else attempt_limit,
        "attemptScope": "per_player_per_map",
    }


def _remaining(db: Database, user_id: str, league_id: int, map_key: dict[str, str], limit: int) -> int:
    with db.connect() as connection:
        row = connection.execute(
            "SELECT used_attempts FROM attempt_budgets WHERE user_id=? AND league_id=? AND map_hash=? AND characteristic=? AND difficulty=?",
            (user_id, league_id, map_key["hash"], map_key["characteristic"], map_key["difficulty"]),
        ).fetchone()
    return max(0, limit - (row["used_attempts"] if row else 0))


def _save_cache(db: Database, projection: dict[str, Any], now: datetime, source_url: str) -> None:
    with db.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO league_qualifier_caches(league_id,qualifier_revision,projection_json,fetched_at,last_error,source_url) VALUES(?,?,?,?,NULL,?) "
            "ON CONFLICT(league_id) DO UPDATE SET qualifier_revision=excluded.qualifier_revision,projection_json=excluded.projection_json,fetched_at=excluded.fetched_at,last_error=NULL,source_url=excluded.source_url",
            (projection["league_id"], projection["qualifier"]["revision"], json.dumps(projection, separators=(",", ":")), utc_text(now), source_url),
        )
        connection.commit()


def _load_cache(db: Database, league_id: int, source_url: str) -> sqlite3.Row | None:
    with db.connect() as connection:
        return connection.execute("SELECT * FROM league_qualifier_caches WHERE league_id=? AND source_url=?", (league_id, source_url)).fetchone()


def _register_reservation(db: Database, user_id: str, key: str, digest: str, now: datetime) -> None:
    with db.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT OR IGNORE INTO reservation_requests(user_id,idempotency_key,request_digest,state,created_at) VALUES(?,?,?,'pending',?)",
            (user_id, key, digest, utc_text(now)),
        )
        row = connection.execute("SELECT request_digest FROM reservation_requests WHERE user_id=? AND idempotency_key=?", (user_id, key)).fetchone()
        connection.commit()
    if row["request_digest"] != digest:
        raise ApiProblem(409, "idempotency_conflict", "Idempotency-Key was already used for another request.")


def _append_audit(db: Database, occurred_at: datetime, user_id: str | None, challenge_id: str | None, event_type: str, details: dict[str, Any]) -> None:
    with db.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO audit_events(occurred_at,user_id,challenge_id,event_type,details_json) VALUES(?,?,?,?,?)",
            (utc_text(occurred_at), user_id, challenge_id, event_type, json.dumps(details, ensure_ascii=False, separators=(",", ":"))),
        )
        connection.commit()


def _reserve_transaction(db: Database, client: LeaderboardClient, settings: Settings, user: sqlite3.Row, key: str, digest: str, body: dict[str, Any], received_at: datetime, count_fetch) -> tuple[int, dict[str, Any]]:
    connection = db.connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        request_row = connection.execute("SELECT * FROM reservation_requests WHERE user_id=? AND idempotency_key=?", (user["user_id"], key)).fetchone()
        if request_row["request_digest"] != digest:
            raise ApiProblem(409, "idempotency_conflict", "Idempotency-Key was already used for another request.")
        if request_row["state"] == "succeeded":
            connection.commit()
            return 200, json.loads(request_row["response_json"])
        count_fetch()
        projection = client.get_sync(body["leagueId"])
        now = settings.clock().astimezone(timezone.utc)
        reason, found_map, _ = _eligibility(projection, body["map"], user["sid"], now, settings)
        if reason != "eligible":
            code_to_status = {"map_not_found": 404}
            raise ApiProblem(code_to_status.get(reason, 403), reason, "The challenge is not eligible.")
        assert found_map is not None
        limit = found_map["qualifier_attempt_limit"]
        connection.execute(
            "INSERT OR IGNORE INTO attempt_budgets(user_id,league_id,map_hash,characteristic,difficulty,attempt_limit,used_attempts,version) VALUES(?,?,?,?,?,?,0,0)",
            (user["user_id"], body["leagueId"], body["map"]["hash"], body["map"]["characteristic"], body["map"]["difficulty"], limit),
        )
        budget = connection.execute(
            "SELECT * FROM attempt_budgets WHERE user_id=? AND league_id=? AND map_hash=? AND characteristic=? AND difficulty=?",
            (user["user_id"], body["leagueId"], body["map"]["hash"], body["map"]["characteristic"], body["map"]["difficulty"]),
        ).fetchone()
        if budget["used_attempts"] >= limit:
            raise ApiProblem(409, "attempts_exhausted", "No qualifier attempts remain.")
        used = budget["used_attempts"] + 1
        connection.execute(
            "UPDATE attempt_budgets SET attempt_limit=?,used_attempts=?,version=version+1 WHERE user_id=? AND league_id=? AND map_hash=? AND characteristic=? AND difficulty=?",
            (limit, used, user["user_id"], body["leagueId"], body["map"]["hash"], body["map"]["characteristic"], body["map"]["difficulty"]),
        )
        challenge_id = str(uuid4())
        reserved_at = settings.clock().astimezone(timezone.utc)
        effective_end = _effective_end(projection)
        accept_until = effective_end + timedelta(seconds=settings.result_grace_seconds)
        response = {
            "schemaVersion": 1, "challengeId": challenge_id, "status": "reserved", "attemptNumber": used,
            "attemptLimit": limit, "remainingAttempts": max(0, limit - used), "reservedAt": utc_text(reserved_at),
            "resultAcceptUntil": utc_text(accept_until), "map": body["map"],
        }
        response_json = json.dumps(response, ensure_ascii=False, separators=(",", ":"))
        connection.execute(
            "INSERT INTO challenges(id,user_id,league_id,map_hash,characteristic,difficulty,qualifier_revision,idempotency_key,request_digest,attempt_number,attempt_limit_at_reserve,status,reserve_received_at,reserved_at,qualifier_end_at,result_accept_until,client_version,game_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,'reserved',?,?,?,?,?,?)",
            (challenge_id, user["user_id"], body["leagueId"], body["map"]["hash"], body["map"]["characteristic"], body["map"]["difficulty"], projection["qualifier"]["revision"], key, digest, used, limit, utc_text(received_at), utc_text(reserved_at), utc_text(effective_end), utc_text(accept_until), body["clientVersion"], body["gameVersion"]),
        )
        connection.execute(
            "UPDATE reservation_requests SET state='succeeded',challenge_id=?,response_json=?,succeeded_at=? WHERE user_id=? AND idempotency_key=?",
            (challenge_id, response_json, utc_text(reserved_at), user["user_id"], key),
        )
        connection.execute(
            "INSERT INTO league_qualifier_caches(league_id,qualifier_revision,projection_json,fetched_at,last_error,source_url) VALUES(?,?,?,?,NULL,?) ON CONFLICT(league_id) DO UPDATE SET qualifier_revision=excluded.qualifier_revision,projection_json=excluded.projection_json,fetched_at=excluded.fetched_at,last_error=NULL,source_url=excluded.source_url",
            (projection["league_id"], projection["qualifier"]["revision"], json.dumps(projection, separators=(",", ":")), utc_text(now), settings.upstream_base_url),
        )
        connection.execute("INSERT INTO audit_events(occurred_at,user_id,challenge_id,event_type,details_json) VALUES(?,?,?,?,?)", (utc_text(reserved_at), user["user_id"], challenge_id, "reserved", json.dumps({"attemptNumber": used, "revision": projection["qualifier"]["revision"]})))
        connection.commit()
        return 201, response
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


REQUIRED_RESULT_KEYS = {
    "schemaVersion", "clientResultId", "challengeId", "map", "endState", "endAction", "endType", "endSongTime",
    "multipliedScore", "modifiedScore", "maxPossibleModifiedScore", "missedCount", "badCutsCount", "goodCutsCount",
    "maxCombo", "fullCombo", "energy", "modifiers", "submissionEligibility", "scoreValidity", "timing", "clientVersion", "gameVersion",
}


def _validate_result_metadata(metadata: Any, path_id: str, key: str) -> dict[str, Any]:
    if not isinstance(metadata, dict) or not REQUIRED_RESULT_KEYS.issubset(metadata) or not set(metadata).issubset(REQUIRED_RESULT_KEYS | {"diagnostics"}) or type(metadata.get("schemaVersion")) is not int or metadata.get("schemaVersion") != 1:
        raise ApiProblem(400, "malformed_request", "Result metadata is incomplete.")
    if require_uuid(metadata["clientResultId"], "clientResultId") != key or require_uuid(metadata["challengeId"], "challengeId") != path_id:
        raise ApiProblem(409, "idempotency_conflict", "Result identifiers do not match the request.")
    metadata = dict(metadata)
    metadata["map"] = normalize_map(metadata["map"])
    if metadata["endState"] not in {"cleared", "failed", "incomplete", "unknown"} or metadata["endAction"] not in {"none", "quit", "restart", "unknown"} or metadata["endType"] not in {"clear", "fail", "quit", "restart", "unknown", "preflight_rejected"}:
        raise ApiProblem(422, "malformed_request", "Result ending fields are invalid.")
    for field in ("endSongTime", "energy"):
        value = metadata[field]
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value in (float("inf"), float("-inf")) or (field == "endSongTime" and value < 0)):
            raise ApiProblem(422, "malformed_request", f"{field} is invalid.")
    for field in ("multipliedScore", "modifiedScore", "maxPossibleModifiedScore", "missedCount", "badCutsCount", "goodCutsCount", "maxCombo"):
        value = metadata[field]
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise ApiProblem(422, "malformed_request", f"{field} is invalid.")
    if metadata["fullCombo"] is not None and type(metadata["fullCombo"]) is not bool:
        raise ApiProblem(422, "malformed_request", "fullCombo is invalid.")
    if metadata["modifiers"] is not None and (not isinstance(metadata["modifiers"], list) or any(not isinstance(value, str) for value in metadata["modifiers"])):
        raise ApiProblem(422, "malformed_request", "modifiers is invalid.")
    if not isinstance(metadata["clientVersion"], str) or not metadata["clientVersion"] or not isinstance(metadata["gameVersion"], str) or not metadata["gameVersion"]:
        raise ApiProblem(422, "malformed_request", "Client version fields are invalid.")
    eligibility = metadata["submissionEligibility"]
    validity = metadata["scoreValidity"]
    if not isinstance(eligibility, dict) or set(eligibility) != {"allowedAtStart", "remainedAllowed", "blockers"} or type(eligibility.get("allowedAtStart")) is not bool or type(eligibility.get("remainedAllowed")) is not bool or not isinstance(eligibility.get("blockers"), list) or any(not isinstance(value, str) for value in eligibility.get("blockers", [])):
        raise ApiProblem(422, "malformed_request", "submissionEligibility is invalid.")
    if not isinstance(validity, dict) or set(validity) != {"validForRanking", "invalidReason", "restartDetected", "playInstanceCount"} or type(validity.get("validForRanking")) is not bool or type(validity.get("restartDetected")) is not bool or isinstance(validity.get("playInstanceCount"), bool) or not isinstance(validity.get("playInstanceCount"), int) or not 0 <= validity["playInstanceCount"] <= 1:
        raise ApiProblem(422, "malformed_request", "scoreValidity is invalid.")
    if eligibility["remainedAllowed"] and not eligibility["allowedAtStart"]:
        raise ApiProblem(422, "malformed_request", "remainedAllowed requires allowedAtStart.")
    reasons = {None, "quit", "restarted", "unknown", "preflight_rejected", "submission_disabled", "replay_unavailable"}
    if validity.get("invalidReason") not in reasons:
        raise ApiProblem(422, "malformed_request", "invalidReason is invalid.")
    ending_contract = {
        "clear": ("cleared", "none"), "fail": ("failed", "none"), "quit": ("incomplete", "quit"),
        "restart": ("incomplete", "restart"), "unknown": ("unknown", "unknown"),
        "preflight_rejected": ("incomplete", "none"),
    }
    if (metadata["endState"], metadata["endAction"]) != ending_contract[metadata["endType"]]:
        raise ApiProblem(422, "malformed_request", "End state/action/type combination is invalid.")
    forced_invalid = metadata["endType"] in {"quit", "restart", "unknown", "preflight_rejected"} or metadata["endAction"] == "restart" or validity["restartDetected"] or validity["playInstanceCount"] != 1 or not eligibility["allowedAtStart"] or not eligibility["remainedAllowed"]
    if forced_invalid and validity["validForRanking"]:
        raise ApiProblem(422, "malformed_request", "This result cannot be ranked.")
    expected_reason = {"quit": "quit", "restart": "restarted", "unknown": "unknown", "preflight_rejected": "preflight_rejected"}.get(metadata["endType"])
    if expected_reason is None and (not eligibility["allowedAtStart"] or not eligibility["remainedAllowed"]):
        expected_reason = "submission_disabled"
    if validity["validForRanking"] and validity["invalidReason"] is not None:
        raise ApiProblem(422, "malformed_request", "A ranking result cannot declare an invalid reason.")
    if expected_reason is not None and validity["invalidReason"] != expected_reason:
        raise ApiProblem(422, "malformed_request", "invalidReason does not follow the ending priority contract.")
    if metadata["endType"] in {"clear", "fail"} and not validity["validForRanking"] and expected_reason is None and validity["invalidReason"] != "replay_unavailable":
        raise ApiProblem(422, "malformed_request", "An unranked clear/fail must identify replay_unavailable.")
    if metadata["endType"] == "restart" and (not validity["restartDetected"] or validity["playInstanceCount"] != 1):
        raise ApiProblem(422, "malformed_request", "Restart metadata is inconsistent.")
    timing = metadata["timing"]
    timing_keys = {"confirmedAtClient", "reserveResponseReceivedAtClient", "startedAtClient", "endedAtClient", "resultFinalizedAtClient", "localSongDurationSeconds", "songSpeedMultiplier", "totalPauseSeconds"}
    if not isinstance(timing, dict) or set(timing) != timing_keys:
        raise ApiProblem(422, "malformed_request", "timing is incomplete.")
    for field in ("confirmedAtClient", "reserveResponseReceivedAtClient", "startedAtClient", "endedAtClient", "resultFinalizedAtClient"):
        if timing[field] is not None:
            try: parse_utc(timing[field])
            except (TypeError, ValueError) as exc: raise ApiProblem(422, "malformed_request", f"{field} is invalid.") from exc
    for field in ("localSongDurationSeconds", "songSpeedMultiplier", "totalPauseSeconds"):
        value = timing[field]
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value in (float("inf"), float("-inf")) or value < 0 or (field != "totalPauseSeconds" and value == 0)):
            raise ApiProblem(422, "malformed_request", f"{field} is invalid.")
    if metadata["endType"] == "preflight_rejected":
        if validity["playInstanceCount"] not in {0, 1}:
            raise ApiProblem(422, "malformed_request", "preflight_rejected playInstanceCount must describe the observed play.")
        if validity["playInstanceCount"] == 0 and timing["startedAtClient"] is not None:
            raise ApiProblem(422, "malformed_request", "An unstarted preflight result cannot have startedAtClient.")
        if validity["playInstanceCount"] == 1 and timing["startedAtClient"] is None:
            raise ApiProblem(422, "malformed_request", "A started preflight result requires startedAtClient.")
    diagnostics = metadata.get("diagnostics")
    if diagnostics is not None and not isinstance(diagnostics, dict):
        raise ApiProblem(422, "malformed_request", "diagnostics is invalid.")
    if isinstance(diagnostics, dict):
        if not set(diagnostics).issubset({"failureCode", "actualMap", "replayGenerationFailed"}):
            raise ApiProblem(422, "malformed_request", "diagnostics contains unknown fields.")
        if diagnostics.get("failureCode") is not None and not isinstance(diagnostics.get("failureCode"), str):
            raise ApiProblem(422, "malformed_request", "diagnostics.failureCode is invalid.")
        if diagnostics.get("replayGenerationFailed") is not None and type(diagnostics.get("replayGenerationFailed")) is not bool:
            raise ApiProblem(422, "malformed_request", "diagnostics.replayGenerationFailed is invalid.")
        if diagnostics.get("actualMap") is not None:
            diagnostics = dict(diagnostics)
            diagnostics["actualMap"] = normalize_map(diagnostics["actualMap"])
            metadata["diagnostics"] = diagnostics
    return metadata


def _deadline_expired(now: datetime, until: datetime, equal_accepted: bool) -> bool:
    return now > until if equal_accepted else now >= until


def _begin_result_transaction(db: Database, settings: Settings, user: sqlite3.Row, challenge_id: str, received_at: datetime) -> sqlite3.Connection:
    connection = db.connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM challenges WHERE id=?", (challenge_id,)).fetchone()
        if row is None:
            raise ApiProblem(404, "challenge_not_found", "Challenge does not exist.")
        if row["user_id"] != user["user_id"]:
            raise ApiProblem(403, "challenge_owner_mismatch", "Challenge belongs to another user.")
        if _deadline_expired(received_at, parse_utc(row["result_accept_until"]), settings.result_deadline_equal_is_accepted):
            if row["status"] in {"reserved", "started"}:
                connection.execute("UPDATE challenges SET status='abandoned' WHERE id=?", (challenge_id,))
            connection.commit()
            raise ApiProblem(409, "result_acceptance_expired", "The result acceptance deadline has passed.")
        if settings.challenge_timeout_seconds is not None and received_at >= parse_utc(row["reserved_at"]) + timedelta(seconds=settings.challenge_timeout_seconds):
            if row["status"] in {"reserved", "started"}:
                connection.execute("UPDATE challenges SET status='abandoned' WHERE id=?", (challenge_id,))
            connection.commit()
            raise ApiProblem(409, "challenge_timed_out", "The configured mock challenge timeout has passed.")
        return connection
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        connection.close()
        raise


def _rollback_and_close(connection: sqlite3.Connection) -> None:
    if connection.in_transaction:
        connection.rollback()
    connection.close()


def _result_transaction(db: Database, settings: Settings, user: sqlite3.Row, challenge_id: str, received_at: datetime, metadata: dict[str, Any], replay: DecodedReplay | None, replay_temp_path: Path | None, connection: sqlite3.Connection | None = None) -> tuple[int, dict[str, Any]]:
    connection = connection or db.connect()
    final_replay_path: Path | None = None
    try:
        if not connection.in_transaction:
            connection.execute("BEGIN IMMEDIATE")
        challenge = connection.execute("SELECT * FROM challenges WHERE id=?", (challenge_id,)).fetchone()
        if challenge is None:
            raise ApiProblem(404, "challenge_not_found", "Challenge does not exist.")
        if challenge["user_id"] != user["user_id"]:
            raise ApiProblem(403, "challenge_owner_mismatch", "Challenge belongs to another user.")
        until = parse_utc(challenge["result_accept_until"])
        if _deadline_expired(received_at, until, settings.result_deadline_equal_is_accepted):
            if challenge["status"] in {"reserved", "started"}:
                connection.execute("UPDATE challenges SET status='abandoned' WHERE id=?", (challenge_id,))
                connection.commit()
            raise ApiProblem(409, "result_acceptance_expired", "The result acceptance deadline has passed.")
        if settings.challenge_timeout_seconds is not None and received_at >= parse_utc(challenge["reserved_at"]) + timedelta(seconds=settings.challenge_timeout_seconds):
            if challenge["status"] in {"reserved", "started"}:
                connection.execute("UPDATE challenges SET status='abandoned' WHERE id=?", (challenge_id,))
                connection.commit()
            raise ApiProblem(409, "challenge_timed_out", "The configured mock challenge timeout has passed.")
        normalized_json = json.dumps(metadata, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        existing = connection.execute("SELECT * FROM results WHERE challenge_id=? OR client_result_id=?", (challenge_id, metadata["clientResultId"])).fetchall()
        if existing:
            exact = next((row for row in existing if row["challenge_id"] == challenge_id and row["client_result_id"] == metadata["clientResultId"]), None)
            if exact is None:
                raise ApiProblem(409, "idempotency_conflict", "clientResultId belongs to another challenge.")
            incoming_sha = replay.sha256 if replay else None
            if exact["metadata_json"] != normalized_json or exact["replay_sha256"] != incoming_sha:
                raise ApiProblem(409, "result_conflict", "A different result is already stored for this challenge.")
            connection.execute("INSERT INTO audit_events(occurred_at,user_id,challenge_id,event_type,details_json) VALUES(?,?,?,?,?)", (utc_text(received_at), user["user_id"], challenge_id, "result_duplicate", json.dumps({"clientResultId": metadata["clientResultId"]})))
            connection.commit()
            return 200, json.loads(exact["response_json"])
        if challenge["status"] not in {"reserved", "started"}:
            raise ApiProblem(409, "challenge_state_conflict", "Challenge cannot accept a result in its current state.")
        expected_map = {"hash": challenge["map_hash"], "characteristic": challenge["characteristic"], "difficulty": challenge["difficulty"]}
        if metadata["map"] != expected_map:
            raise ApiProblem(422, "replay_mismatch", "Result MapKey does not match the challenge.")
        validity = metadata["scoreValidity"]
        ranking = validity["validForRanking"]
        requires_replay = metadata["endType"] in {"clear", "fail"} and ranking
        if requires_replay and replay is None:
            raise ApiProblem(422, "replay_invalid", "A ranking candidate requires a BSOR replay.")
        if validity["invalidReason"] == "replay_unavailable" and replay is not None:
            raise ApiProblem(422, "replay_invalid", "replay_unavailable cannot include a replay.")
        if replay:
            provider_platforms = {"steamTicket": {"steam", "Steam"}, "oculusTicket": {"oculus", "Oculus", "oculuspc", "OculusPC"}}
            if replay.info.player_id != user["sid"] or replay.info.platform not in provider_platforms.get(user["auth_provider"], set()) or replay.info.hash != challenge["map_hash"] or replay.info.mode != challenge["characteristic"] or replay.info.difficulty != challenge["difficulty"]:
                raise ApiProblem(422, "replay_mismatch", "Replay identity or MapKey does not match the challenge.")
        result_id = str(uuid4())
        if replay is not None and replay_temp_path is not None:
            final_replay_path = settings.replay_dir / f"{result_id}.bsor"
            replay_temp_path.replace(final_replay_path)
        budget = connection.execute(
            "SELECT attempt_limit,used_attempts FROM attempt_budgets WHERE user_id=? AND league_id=? AND map_hash=? AND characteristic=? AND difficulty=?",
            (challenge["user_id"], challenge["league_id"], challenge["map_hash"], challenge["characteristic"], challenge["difficulty"]),
        ).fetchone()
        remaining = max(0, budget["attempt_limit"] - budget["used_attempts"])
        response = {
            "schemaVersion": 1, "submissionId": result_id, "challengeId": challenge_id, "status": "submitted",
            "validForRanking": ranking, "invalidReason": validity["invalidReason"], "receivedAt": utc_text(received_at),
            "replaySha256": replay.sha256 if replay else None, "remainingAttempts": remaining,
        }
        response_json = json.dumps(response, ensure_ascii=False, separators=(",", ":"))
        eligibility = metadata["submissionEligibility"]
        connection.execute(
            "INSERT INTO results(id,challenge_id,client_result_id,metadata_json,response_json,end_state,end_action,end_type,multiplied_score,modified_score,max_possible_modified_score,missed_count,bad_cuts_count,good_cuts_count,max_combo,full_combo,energy,modifiers_json,submission_allowed_at_start,remained_allowed,valid_for_ranking,invalid_reason,restart_detected,play_instance_count,replay_sha256,replay_size,received_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (result_id, challenge_id, metadata["clientResultId"], normalized_json, response_json, metadata["endState"], metadata["endAction"], metadata["endType"], metadata["multipliedScore"], metadata["modifiedScore"], metadata["maxPossibleModifiedScore"], metadata["missedCount"], metadata["badCutsCount"], metadata["goodCutsCount"], metadata["maxCombo"], metadata["fullCombo"], metadata["energy"], json.dumps(metadata["modifiers"]), eligibility["allowedAtStart"], eligibility["remainedAllowed"], ranking, validity["invalidReason"], validity["restartDetected"], validity["playInstanceCount"], replay.sha256 if replay else None, replay.byte_count if replay else None, utc_text(received_at)),
        )
        if replay and final_replay_path:
            connection.execute("INSERT INTO replay_blobs(result_id,storage_path,byte_count,sha256,stored_at) VALUES(?,?,?,?,?)", (result_id, str(final_replay_path), replay.byte_count, replay.sha256, utc_text(received_at)))
        connection.execute("UPDATE challenges SET status='submitted',submitted_at=? WHERE id=?", (utc_text(received_at), challenge_id))
        connection.execute("INSERT INTO audit_events(occurred_at,user_id,challenge_id,event_type,details_json) VALUES(?,?,?,?,?)", (utc_text(received_at), user["user_id"], challenge_id, "submitted", json.dumps({"validForRanking": ranking})))
        connection.commit()
        return 201, response
    except BaseException:
        connection.rollback()
        if final_replay_path is not None and final_replay_path.exists():
            final_replay_path.unlink()
        raise
    finally:
        connection.close()


def create_app(settings: Settings | None = None, leaderboard_client: LeaderboardClient | None = None, *, control=None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.validate()
    db = Database(settings.database_path, settings.sqlite_busy_timeout_ms)
    settings.replay_dir.mkdir(parents=True, exist_ok=True)
    client = leaderboard_client or LeaderboardClient(settings, control=control)
    app = FastAPI(title="JBSL Qualifier Score Manager (TEST ONLY / 本番利用禁止)", version="1", docs_url=None, redoc_url=None)
    app.state.settings = settings; app.state.db = db; app.state.client = client
    app.state.counts = {"authSession": 0, "authMe": 0, "authDelete": 0, "status": 0, "reserve": 0, "started": 0, "result": 0, "jbslLeaderboardFetch": 0}
    app.state.count_lock = threading.Lock(); app.state.rate_limiter = RateLimiter(settings.rate_limit_enabled)

    def increment(name: str) -> None:
        with app.state.count_lock: app.state.counts[name] += 1

    @app.exception_handler(ApiProblem)
    async def handle_problem(request: Request, exc: ApiProblem) -> JSONResponse:
        request_id = getattr(request.state, "mock_request_id", None) or str(uuid4())
        path = request.url.path
        event_type = None
        if path.endswith("/result"):
            event_type = "result_rejected"
        elif path == "/api/v1/qualifiers/challenges" and request.method == "POST":
            event_type = "reserve_rejected"
        elif path == "/api/v1/auth/session" and request.method == "POST":
            event_type = "authentication_rejected"
        if event_type:
            try:
                await run_in_threadpool(
                    _append_audit, db, settings.clock().astimezone(timezone.utc),
                    getattr(request.state, "audit_user_id", None), request.path_params.get("challenge_id"),
                    event_type, {"code": exc.code, "requestId": request_id},
                )
            except Exception:
                LOG.exception("failed to append a secret-free audit event")
        return problem_response(exc, request_id)

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        LOG.exception("mock server request failed without request payload data")
        return problem_response(ApiProblem(500, "internal_error", "Unexpected mock server error."))

    @app.middleware("http")
    async def common_headers(request: Request, call_next):
        if request.url.hostname not in {"127.0.0.1", "localhost", "testserver"}:
            return problem_response(ApiProblem(403, "malformed_request", "TEST ONLY server accepts loopback requests only."))
        if request.url.scheme == "http" and not settings.allow_insecure_loopback_cookie:
            return problem_response(ApiProblem(403, "malformed_request", "HTTP loopback requires the explicit development setting."))
        response = await call_next(request)
        response.headers["X-JBSL-Mock-Server"] = "true"; response.headers["Cache-Control"] = "no-store"
        response.headers.setdefault("X-Request-ID", str(uuid4()))
        return response

    async def authenticated(request: Request, route: str) -> sqlite3.Row:
        now = settings.clock().astimezone(timezone.utc)
        user = await run_in_threadpool(_get_session, db, request.cookies.get("jbslq_session"), now)
        request.state.audit_user_id = user["user_id"]
        app.state.rate_limiter.check(route, user["sid"], now, enabled=settings.rate_limit_enabled if control else None)
        return user

    @app.post("/api/v1/auth/session")
    async def auth_session(request: Request):
        increment("authSession"); now = settings.clock().astimezone(timezone.utc)
        app.state.rate_limiter.check("authSession", _request_identity(request), now, enabled=settings.rate_limit_enabled if control else None)
        form = await request.form(); ticket = form.get("ticket"); provider = form.get("provider"); return_url = form.get("returnUrl", "/")
        if not isinstance(ticket, str) or len(ticket) > 8192 or not isinstance(provider, str) or return_url != "/":
            raise ApiProblem(400, "malformed_request", "Authentication form is invalid.")
        identity = stub.verify(ticket, provider, settings.stub_sid, settings.stub_display_name) if settings.auth_mode == "stub" else await run_in_threadpool(real_provider.verify, ticket, provider, settings)
        token = secrets.token_urlsafe(32); user_id = str(uuid4()); expires = now + timedelta(seconds=settings.session_seconds)
        def save_session():
            with db.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute("SELECT id FROM users WHERE sid=?", (identity.sid,)).fetchone()
                actual_id = existing["id"] if existing else user_id
                if existing:
                    connection.execute("UPDATE users SET display_name=?,updated_at=? WHERE id=?", (identity.display_name, utc_text(now), actual_id))
                else:
                    connection.execute("INSERT INTO users VALUES(?,?,?,?,?)", (actual_id, identity.sid, identity.display_name, utc_text(now), utc_text(now)))
                connection.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?,NULL)", (session_hash(token), actual_id, identity.provider, utc_text(now), utc_text(now), utc_text(expires)))
                connection.execute("INSERT INTO audit_events(occurred_at,user_id,challenge_id,event_type,details_json) VALUES(?,?,NULL,'authentication_succeeded',?)", (utc_text(now), actual_id, json.dumps({"provider": identity.provider})))
                connection.commit()
        await run_in_threadpool(save_session)
        response = _json_response({"schemaVersion": 1, "authenticated": True, "user": {"sid": identity.sid, "displayName": identity.display_name}, "expiresAt": utc_text(expires), "testOnly": True})
        response.set_cookie("jbslq_session", token, path="/", httponly=True, secure=not settings.allow_insecure_loopback_cookie, samesite="lax")
        return response

    @app.get("/api/v1/auth/me")
    async def auth_me(request: Request):
        increment("authMe"); user = await authenticated(request, "authMe")
        return {"schemaVersion": 1, "authenticated": True, "user": {"sid": user["sid"], "displayName": user["display_name"]}, "expiresAt": user["expires_at"]}

    @app.delete("/api/v1/auth/session")
    async def auth_delete(request: Request):
        increment("authDelete"); user = await authenticated(request, "authMe"); now = settings.clock().astimezone(timezone.utc)
        def revoke():
            with db.connect() as connection:
                connection.execute("BEGIN IMMEDIATE"); connection.execute("UPDATE sessions SET revoked_at=? WHERE id_hash=?", (utc_text(now), user["id_hash"])); connection.commit()
        await run_in_threadpool(revoke)
        response = Response(status_code=204); response.delete_cookie("jbslq_session", path="/", secure=not settings.allow_insecure_loopback_cookie, httponly=True, samesite="lax")
        return response

    @app.get("/api/v1/qualifiers/status")
    async def qualifier_status(request: Request):
        increment("status"); user = await authenticated(request, "status"); now = settings.clock().astimezone(timezone.utc)
        query = request.query_params
        try:
            league_raw = query["leagueId"]
            if not league_raw.isdigit() or league_raw.startswith("0"): raise ValueError()
            league_id = int(league_raw)
            map_key = normalize_map({"hash": query["hash"], "characteristic": query["characteristic"], "difficulty": query["difficulty"]})
        except (KeyError, ValueError):
            raise ApiProblem(400, "malformed_request", "Status query is invalid.")
        cache_row = await run_in_threadpool(_load_cache, db, league_id, settings.upstream_base_url)
        projection = None; fetched_at = None; stale = False
        if cache_row:
            fetched_at = parse_utc(cache_row["fetched_at"]); age = (now - fetched_at).total_seconds()
            if age <= settings.cache_fresh_seconds: projection = json.loads(cache_row["projection_json"])
        if projection is None:
            increment("jbslLeaderboardFetch")
            try:
                projection = await client.get_async(league_id); fetched_at = now
                await run_in_threadpool(_save_cache, db, projection, now, settings.upstream_base_url)
            except ApiProblem as exc:
                if exc.code == "league_not_found":
                    return {"schemaVersion": 1, "serverTime": utc_text(now), "eligible": False, "reasonCode": "league_not_found", "league": None, "map": None, "isParticipant": None, "remainingAttempts": None, "cache": {"fetchedAt": None, "stale": False}}
                if exc.code == "upstream_unavailable" and cache_row and (now - parse_utc(cache_row["fetched_at"])).total_seconds() <= settings.cache_stale_seconds:
                    projection = json.loads(cache_row["projection_json"]); fetched_at = parse_utc(cache_row["fetched_at"]); stale = True
                else: raise
        reason, found_map, participant = _eligibility(projection, map_key, user["sid"], now, settings)
        remaining = None
        if found_map is not None and found_map["qualifier_attempt_limit"] is not None and reason in {"eligible", "league_not_open", "outside_qualifier_window"}:
            remaining = await run_in_threadpool(_remaining, db, user["user_id"], league_id, map_key, found_map["qualifier_attempt_limit"])
        eligible = reason == "eligible"
        if stale:
            reason = "upstream_unavailable"
        elif eligible and remaining == 0:
            reason = "attempts_exhausted"
        return {"schemaVersion": 1, "serverTime": utc_text(now), "eligible": eligible, "reasonCode": reason, "league": _league_body(projection), "map": _map_body(found_map) if found_map else None, "isParticipant": participant, "remainingAttempts": remaining, "cache": {"fetchedAt": utc_text(fetched_at), "stale": stale}}

    @app.post("/api/v1/qualifiers/challenges")
    async def reserve(request: Request):
        increment("reserve"); received_at = settings.clock().astimezone(timezone.utc); user = await authenticated(request, "reserve")
        key = require_uuid(request.headers.get("Idempotency-Key"), "Idempotency-Key")
        try: raw = await request.json()
        except Exception as exc: raise ApiProblem(400, "malformed_request", "Request body must be JSON.") from exc
        if not isinstance(raw, dict) or set(raw) != {"schemaVersion", "leagueId", "map", "clientVersion", "gameVersion"} or type(raw.get("schemaVersion")) is not int or raw.get("schemaVersion") != 1 or not isinstance(raw.get("clientVersion"), str) or not raw.get("clientVersion") or not isinstance(raw.get("gameVersion"), str) or not raw.get("gameVersion"):
            raise ApiProblem(400, "malformed_request", "Reserve request is invalid.")
        body = dict(raw); body["leagueId"] = require_positive_int(body["leagueId"], "leagueId"); body["map"] = normalize_map(body["map"])
        digest = canonical_digest(body)
        await run_in_threadpool(_register_reservation, db, user["user_id"], key, digest, received_at)
        status, response = await run_in_threadpool(_reserve_transaction, db, client, settings, user, key, digest, body, received_at, lambda: increment("jbslLeaderboardFetch"))
        return _json_response(response, status)

    @app.post("/api/v1/qualifiers/challenges/{challenge_id}/started")
    async def started(challenge_id: str, request: Request):
        increment("started"); now = settings.clock().astimezone(timezone.utc); user = await authenticated(request, "started"); challenge_id = require_uuid(challenge_id, "challengeId")
        try: raw = await request.json()
        except Exception as exc: raise ApiProblem(400, "malformed_request", "Request body must be JSON.") from exc
        if not isinstance(raw, dict) or set(raw) != {"schemaVersion", "actualMap", "gameMode", "practice", "submissionAllowed", "startedAtClient"} or type(raw.get("schemaVersion")) is not int or raw.get("schemaVersion") != 1:
            raise ApiProblem(400, "malformed_request", "Started request is invalid.")
        normalized = dict(raw); normalized["actualMap"] = normalize_map(raw["actualMap"])
        if raw["gameMode"] != "Solo" or raw["practice"] is not False or raw["submissionAllowed"] is not True:
            raise ApiProblem(422, "challenge_state_conflict", "Started conditions are invalid.")
        try: parse_utc(raw["startedAtClient"])
        except (TypeError, ValueError) as exc: raise ApiProblem(422, "malformed_request", "startedAtClient is invalid.") from exc
        request_json = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        def transition():
            with db.connect() as connection:
                connection.execute("BEGIN IMMEDIATE"); row = connection.execute("SELECT * FROM challenges WHERE id=?", (challenge_id,)).fetchone()
                if row is None: raise ApiProblem(404, "challenge_not_found", "Challenge does not exist.")
                if row["user_id"] != user["user_id"]: raise ApiProblem(403, "challenge_owner_mismatch", "Challenge belongs to another user.")
                expected = {"hash": row["map_hash"], "characteristic": row["characteristic"], "difficulty": row["difficulty"]}
                if normalized["actualMap"] != expected: raise ApiProblem(422, "replay_mismatch", "Started MapKey does not match.")
                if row["status"] == "started":
                    if row["started_request_json"] != request_json: raise ApiProblem(409, "challenge_state_conflict", "A different started request was already accepted.")
                    connection.commit(); return {"schemaVersion": 1, "challengeId": challenge_id, "status": "started", "startedAt": row["started_at"]}
                if row["status"] != "reserved": raise ApiProblem(409, "challenge_state_conflict", "Challenge cannot be started.")
                started_at = utc_text(now); connection.execute("UPDATE challenges SET status='started',started_at=?,started_request_json=? WHERE id=?", (started_at, request_json, challenge_id)); connection.execute("INSERT INTO audit_events(occurred_at,user_id,challenge_id,event_type,details_json) VALUES(?,?,?,'started','{}')", (started_at, user["user_id"], challenge_id)); connection.commit()
                return {"schemaVersion": 1, "challengeId": challenge_id, "status": "started", "startedAt": started_at}
        return await run_in_threadpool(transition)

    @app.put("/api/v1/qualifiers/challenges/{challenge_id}/result")
    async def result(challenge_id: str, request: Request):
        increment("result"); received_at = settings.clock().astimezone(timezone.utc); user = await authenticated(request, "result"); challenge_id = require_uuid(challenge_id, "challengeId")
        # SQLite's write lock stays owned from receipt validation through payload
        # validation and commit. Other requests wait in worker threads, not on the
        # async event loop, and cannot abandon this challenge halfway through.
        locked_connection = await run_in_threadpool(_begin_result_transaction, db, settings, user, challenge_id, received_at)
        temp_path = None
        try:
            content_length = request.headers.get("content-length")
            multipart_limit = settings.compressed_replay_limit + settings.metadata_limit + 1024 * 1024
            if content_length is not None:
                try:
                    if int(content_length) > multipart_limit: raise ApiProblem(413, "replay_too_large", "Multipart body exceeds the configured limit.")
                except ValueError as exc: raise ApiProblem(400, "malformed_request", "Content-Length is invalid.") from exc
            original_receive = request._receive
            received_bytes = 0
            async def limited_receive():
                nonlocal received_bytes
                message = await original_receive()
                if message.get("type") == "http.request":
                    received_bytes += len(message.get("body", b""))
                    if received_bytes > multipart_limit:
                        raise ApiProblem(413, "replay_too_large", "Multipart body exceeds the configured limit.")
                return message
            request._receive = limited_receive
            form = await request.form(max_files=2, max_fields=1, max_part_size=max(settings.compressed_replay_limit, settings.metadata_limit)); parts = list(form.multi_items())
            if sum(1 for name, _ in parts if name == "metadata") != 1 or sum(1 for name, _ in parts if name == "replay") > 1 or any(name not in {"metadata", "replay"} for name, _ in parts):
                raise ApiProblem(400, "malformed_request", "Multipart parts are invalid.")
            metadata_part = form["metadata"]
            if isinstance(metadata_part, UploadFile): metadata_bytes = await metadata_part.read(settings.metadata_limit + 1)
            else: metadata_bytes = str(metadata_part).encode("utf-8")
            if len(metadata_bytes) > settings.metadata_limit: raise ApiProblem(413, "malformed_request", "Metadata is too large.")
            try: metadata = _validate_result_metadata(json.loads(metadata_bytes), challenge_id, require_uuid(request.headers.get("Idempotency-Key"), "Idempotency-Key"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc: raise ApiProblem(400, "malformed_request", "Metadata is not valid UTF-8 JSON.") from exc
            replay = None
            replay_part = form.get("replay")
            if replay_part is not None:
                if not isinstance(replay_part, UploadFile): raise ApiProblem(400, "malformed_request", "Replay must be a file part.")
                compressed = await replay_part.read(settings.compressed_replay_limit + 1)
                replay = await run_in_threadpool(decode_gzip, compressed, settings.compressed_replay_limit, settings.expanded_replay_limit)
            temp_path = settings.replay_dir / f".{uuid4()}.tmp" if replay else None
            if replay and temp_path:
                def store():
                    with temp_path.open("wb") as stream: stream.write(replay.data); stream.flush(); os.fsync(stream.fileno())
                await run_in_threadpool(store)
            connection_for_finish = locked_connection
            locked_connection = None
            status, response = await run_in_threadpool(_result_transaction, db, settings, user, challenge_id, received_at, metadata, replay, temp_path, connection_for_finish)
        finally:
            if locked_connection is not None:
                await run_in_threadpool(_rollback_and_close, locked_connection)
            if temp_path and temp_path.exists(): temp_path.unlink()
        return _json_response(response, status)

    @app.get("/healthz")
    async def health():
        healthy = await run_in_threadpool(db.health)
        return {"status": "ok" if healthy else "error", "testOnly": True, "database": "ok" if healthy else "error"}

    @app.get("/__mock__/state")
    async def mock_state():
        now = settings.clock().astimezone(timezone.utc)
        def state_db():
            with db.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                expired = connection.execute("SELECT id,result_accept_until FROM challenges WHERE status IN ('reserved','started')").fetchall()
                for row in expired:
                    if _deadline_expired(now, parse_utc(row["result_accept_until"]), settings.result_deadline_equal_is_accepted): connection.execute("UPDATE challenges SET status='abandoned' WHERE id=?", (row["id"],))
                budgets = [dict(row) for row in connection.execute("SELECT u.sid,b.* FROM attempt_budgets b JOIN users u ON u.id=b.user_id ORDER BY b.league_id,b.map_hash")]
                states = {name: connection.execute("SELECT COUNT(*) FROM challenges WHERE status=?", (name,)).fetchone()[0] for name in ("reserved", "started", "submitted", "abandoned")}
                connection.commit()
            return [{"sid": b["sid"], "leagueId": b["league_id"], "map": {"hash": b["map_hash"], "characteristic": b["characteristic"], "difficulty": b["difficulty"]}, "attemptLimit": b["attempt_limit"], "usedAttempts": b["used_attempts"], "remainingAttempts": max(0, b["attempt_limit"] - b["used_attempts"])} for b in budgets], states
        budgets, states = await run_in_threadpool(state_db)
        with app.state.count_lock: counts = dict(app.state.counts)
        return {"schemaVersion": 1, "testOnly": True, "requestCounts": counts, "budgets": budgets, "challengeCounts": states, "deadlineProfile": {"resultGraceSeconds": settings.result_grace_seconds, "equalAccepted": settings.result_deadline_equal_is_accepted, "receivedClockPoint": "request_handler_entry"}, "bsorScoreValidationProfile": settings.bsor_score_validation_profile}

    from .documentation import install_docs
    install_docs(app, "score")
    if control is not None:
        from .traffic import DebugTraffic
        app.add_middleware(DebugTraffic, control=control, role="score")
    LOG.warning("TEST ONLY / 本番利用禁止: score manager initialized")
    return app

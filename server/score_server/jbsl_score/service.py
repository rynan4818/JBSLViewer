from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict
from datetime import datetime, timezone
from uuid import uuid4

from .config import Policy
from .contracts import canonical_digest, normalize_map, parse_utc, require_positive_int, utc_text
from .database import Database, dumps
from .errors import ApiProblem
from .locks import FileLock
from .timing import measure_operation
from .upstream import LeaderboardClient, TicketVerifier


def timestamp(value):
    return utc_text(datetime.fromtimestamp(value, timezone.utc)) if value is not None else None


def map_of(row):
    return {"hash": row["map_hash"], "characteristic": row["characteristic"], "difficulty": row["difficulty"]}


def budget_key(sid, league_id, key):
    return sid, league_id, key["hash"], key["characteristic"], key["difficulty"]


BUDGET_WHERE = "sid=? AND league_id=? AND map_hash=? AND characteristic=? AND difficulty=?"


class Service:
    def __init__(self, config, upstream=None, verifier=None, clock=time.time):
        self.config = config.validate()
        self.clock = clock
        self.lock_dir = config.data_dir / "locks"
        with FileLock(self.lock_dir, "schema"):
            self.db = Database(config.data_dir / "score.sqlite3")
        self.upstream = upstream or LeaderboardClient(config)
        self.verifier = verifier or TicketVerifier(config)

    def challenge_lock(self, challenge_id):
        return FileLock(self.lock_dir, "challenge:" + challenge_id)

    def check_disk(self, policy):
        if shutil.disk_usage(self.config.data_dir).free < policy.min_free_disk_mb * 1024 * 1024:
            raise ApiProblem(503, "storage_unavailable", "Free disk space is below the configured minimum.")

    def fetch_projection(self, league_id):
        try:
            projection = self.upstream.get(league_id)
        except ApiProblem as problem:
            with self.db.transaction() as c:
                if problem.code == "league_not_found":
                    c.execute("DELETE FROM league_cache WHERE league_id=?", (league_id,))
                else:
                    c.execute("UPDATE league_cache SET last_error=? WHERE league_id=?", (problem.code, league_id))
            raise
        now = self.clock()
        with self.db.transaction() as c:
            c.execute(
                "INSERT INTO league_cache VALUES(?,?,?,NULL) ON CONFLICT(league_id) DO UPDATE SET "
                "projection_json=excluded.projection_json,fetched_at=excluded.fetched_at,last_error=NULL",
                (league_id, dumps(projection), now),
            )
            c.executemany(
                "UPDATE users SET display_name=?,updated_at=? WHERE sid=? AND display_name=sid",
                [(name, now, sid) for sid, name in projection.get("player_names", {}).items()],
            )
        return projection, now

    def resolve_player_name(self, c, sid, display_name):
        if display_name != sid:
            return display_name
        existing = c.execute("SELECT display_name FROM users WHERE sid=?", (sid,)).fetchone()
        if existing and existing["display_name"] != sid:
            return existing["display_name"]
        for cache in c.execute("SELECT projection_json FROM league_cache ORDER BY fetched_at DESC,league_id"):
            name = json.loads(cache["projection_json"]).get("player_names", {}).get(sid)
            if name:
                return name
        return sid

    def eligibility(self, projection, key, sid, policy, now):
        q = projection["qualifier"]
        found = next((m for m in projection["maps"] if all(m[k] == v for k, v in key.items())), None)
        participant = any(p["sid"] == sid for p in projection["participants"])
        end = parse_utc(q["ends_at"] or projection["end"]).timestamp()
        start = parse_utc(q["starts_at"], nullable=True)
        deadline = end
        if policy.start_deadline_policy == "end_minus_duration" and found:
            duration = found["song_duration_seconds"]
            # Missing duration fails closed under the stricter optional policy.
            deadline = end - duration if duration is not None else float("-inf")
        if not q["enabled"]:
            reason = "qualifier_disabled"
        elif q["submission_method"] != "jbsl_qualifier_v1":
            reason = "wrong_submission_method"
        elif not projection["isLive"] or not projection["isOpen"] or not policy.reservations_enabled:
            reason = "league_not_open"
        elif (start and now < start.timestamp()) or now > deadline:
            reason = "outside_qualifier_window"
        elif found is None:
            reason = "map_not_found"
        elif not participant:
            reason = "not_participant"
        else:
            reason = "eligible"
        return reason, found, participant, end

    def status(self, sid, league_id, key):
        now = self.clock()
        policy, _ = self.db.policy()
        with self.db.read() as c:
            cache = c.execute("SELECT * FROM league_cache WHERE league_id=?", (league_id,)).fetchone()
        stale = False
        if cache and 0 <= now - cache["fetched_at"] <= policy.cache_fresh_seconds:
            projection, fetched_at = json.loads(cache["projection_json"]), cache["fetched_at"]
        else:
            try:
                projection, fetched_at = self.fetch_projection(league_id)
            except ApiProblem as problem:
                if problem.code == "league_not_found":
                    # The existing Viewer StrictJson parser requires a timestamp even for 404 status.
                    return {
                        "schemaVersion": 1,
                        "serverTime": timestamp(now),
                        "eligible": False,
                        "reasonCode": "league_not_found",
                        "league": None,
                        "map": None,
                        "isParticipant": None,
                        "remainingAttempts": None,
                        "cache": {"fetchedAt": timestamp(now), "stale": False},
                    }
                if (
                    problem.code != "upstream_unavailable"
                    or not cache
                    or now - cache["fetched_at"] > policy.cache_stale_seconds
                ):
                    raise
                projection, fetched_at, stale = json.loads(cache["projection_json"]), cache["fetched_at"], True
        now = self.clock()
        reason, found, participant, _ = self.eligibility(projection, key, sid, policy, now)
        remaining = None
        if (
            found
            and found["qualifier_attempt_limit"] is not None
            and reason in ("eligible", "league_not_open", "outside_qualifier_window")
        ):
            with self.db.read() as c:
                budget = c.execute(
                    "SELECT used FROM budgets WHERE " + BUDGET_WHERE, budget_key(sid, league_id, key)
                ).fetchone()
            remaining = max(0, found["qualifier_attempt_limit"] - (budget[0] if budget else 0))
        eligible = reason == "eligible"
        if stale:
            reason = "upstream_unavailable"
        elif eligible and remaining == 0:
            reason = "attempts_exhausted"
        return {
            "schemaVersion": 1,
            "serverTime": timestamp(now),
            "eligible": eligible,
            "reasonCode": reason,
            "league": {
                "id": league_id,
                "name": projection["league_title"],
                "submissionMethod": projection["qualifier"]["submission_method"],
                "revision": projection["qualifier"]["revision"],
            },
            "map": {
                **key,
                "title": found.get("title"),
                "attemptLimit": found["qualifier_attempt_limit"],
                "attemptScope": "per_player_per_map",
            }
            if found
            else None,
            "isParticipant": participant,
            "remainingAttempts": remaining,
            "cache": {"fetchedAt": timestamp(fetched_at), "stale": stale},
        }

    @measure_operation()
    def reserve(self, user, key, body, request_id):
        if (
            not isinstance(body, dict)
            or set(body) != {"schemaVersion", "leagueId", "map", "clientVersion", "gameVersion"}
            or type(body.get("schemaVersion")) is not int
            or body["schemaVersion"] != 1
        ):
            raise ApiProblem(400, "malformed_request", "Reserve schema is invalid.")
        for name in ("clientVersion", "gameVersion"):
            if not isinstance(body[name], str) or not 1 <= len(body[name]) <= 100:
                raise ApiProblem(400, "malformed_request", "Client version is invalid.")
        body = {
            **body,
            "leagueId": require_positive_int(body["leagueId"], "leagueId"),
            "map": normalize_map(body["map"]),
        }
        digest = canonical_digest(body)
        sid, league_id, received = user["sid"], body["leagueId"], self.clock()
        # Same-key calls serialize across processes; network I/O never owns SQLite's writer lock.
        with FileLock(self.lock_dir, "reserve:" + sid + ":" + key):
            with self.db.read() as c:
                previous = c.execute("SELECT * FROM challenges WHERE sid=? AND reserve_key=?", (sid, key)).fetchone()
            if previous:
                if previous["request_digest"] != digest:
                    raise ApiProblem(409, "idempotency_conflict", "This reservation key has different content.")
                return 200, previous["response_json"]
            with self.db.transaction() as c:
                c.execute("INSERT OR IGNORE INTO reservation_requests VALUES(?,?,?,?)", (sid, key, digest, received))
                binding = c.execute(
                    "SELECT digest FROM reservation_requests WHERE sid=? AND key=?", (sid, key)
                ).fetchone()
                if binding["digest"] != digest:
                    raise ApiProblem(409, "idempotency_conflict", "This reservation key has different content.")
            projection, _ = self.fetch_projection(league_id)
            with self.db.transaction() as c:
                policy_row = c.execute("SELECT * FROM policy WHERE id=1").fetchone()
                policy = Policy.parse(json.loads(policy_row["value_json"]))
                self.check_disk(policy)
                now = self.clock()
                reason, found, _, end = self.eligibility(projection, body["map"], sid, policy, now)
                if reason != "eligible":
                    raise ApiProblem(404 if reason == "map_not_found" else 403, reason, "Challenge is not eligible.")
                if policy.max_active_per_user:
                    active = c.execute(
                        "SELECT COUNT(*) FROM challenges WHERE sid=? AND status IN ('reserved','started') "
                        "AND accept_until>=? AND (timeout_at IS NULL OR timeout_at>?)",
                        (sid, now, now),
                    ).fetchone()[0]
                    if active >= policy.max_active_per_user:
                        raise ApiProblem(
                            409, "challenge_state_conflict", "The configured active challenge limit was reached."
                        )
                args = budget_key(sid, league_id, body["map"])
                limit = found["qualifier_attempt_limit"]
                c.execute("INSERT OR IGNORE INTO budgets VALUES(?,?,?,?,?,0,0,?)", (*args, limit))
                budget = c.execute("SELECT * FROM budgets WHERE " + BUDGET_WHERE, args).fetchone()
                if budget["used"] >= limit:
                    raise ApiProblem(409, "attempts_exhausted", "No qualifier attempts remain.")
                used, number = budget["used"] + 1, budget["total"] + 1
                c.execute(
                    "UPDATE budgets SET used=?,total=?,last_limit=? WHERE " + BUDGET_WHERE, (used, number, limit, *args)
                )
                challenge_id = str(uuid4())
                accept_until = end + policy.result_grace_seconds
                response = dumps(
                    {
                        "schemaVersion": 1,
                        "challengeId": challenge_id,
                        "status": "reserved",
                        "attemptNumber": number,
                        "attemptLimit": limit,
                        "remainingAttempts": limit - used,
                        "reservedAt": timestamp(now),
                        "resultAcceptUntil": timestamp(accept_until),
                        "map": body["map"],
                    }
                )
                c.execute(
                    "INSERT INTO challenges(id,sid,league_id,map_hash,characteristic,difficulty,revision,reserve_key,"
                    "request_digest,response_json,attempt_number,attempt_limit,status,reserved_at,received_at,"
                    "effective_end,accept_until,timeout_at,policy_json,policy_revision,provider,client_version,game_version) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'reserved',?,?,?,?,?,?,?,?,?,?)",
                    (
                        challenge_id,
                        *args,
                        projection["qualifier"]["revision"],
                        key,
                        digest,
                        response,
                        number,
                        limit,
                        now,
                        received,
                        end,
                        accept_until,
                        now + policy.challenge_timeout_seconds if policy.challenge_timeout_seconds else None,
                        policy_row["value_json"],
                        policy_row["revision"],
                        user["provider"],
                        body["clientVersion"],
                        body["gameVersion"],
                    ),
                )
                self.db.audit(
                    now,
                    sid,
                    "reserved",
                    challenge_id,
                    request_id,
                    {"attemptNumber": number, "policyRevision": policy_row["revision"]},
                    c,
                )
            return 201, response

    def owned_challenge(self, sid, challenge_id, connection=None):
        if connection is None:
            with self.db.read() as c:
                return self.owned_challenge(sid, challenge_id, c)
        row = connection.execute("SELECT * FROM challenges WHERE id=?", (challenge_id,)).fetchone()
        if row is None:
            raise ApiProblem(404, "challenge_not_found", "Challenge does not exist.")
        if row["sid"] != sid:
            raise ApiProblem(403, "challenge_owner_mismatch", "Challenge belongs to another user.")
        return row

    def check_deadline(self, row, now):
        if now > row["accept_until"]:
            raise ApiProblem(409, "result_acceptance_expired", "The result acceptance deadline has passed.")
        # Timeout applies only to unsubmitted plays. Successful retries retain their receipt until accept_until.
        if row["status"] != "submitted" and row["timeout_at"] is not None and now >= row["timeout_at"]:
            raise ApiProblem(409, "challenge_timed_out", "The challenge timed out.")
        if row["status"] == "abandoned":
            if row["abandoned_reason"] == "admin_force_ended":
                raise ApiProblem(409, "admin_force_ended", "管理者がこのチャレンジを強制終了しました。")
            raise ApiProblem(409, row["abandoned_reason"] or "challenge_timed_out", "The challenge is closed.")

    def admission(self, sid, challenge_id):
        """Caller owns the OS challenge lock through upload validation and commit."""
        row = self.owned_challenge(sid, challenge_id)
        now = self.clock()
        self.check_deadline(row, now)
        return now

    @measure_operation()
    def started(self, user, challenge_id, body, request_id):
        with self.challenge_lock(challenge_id):
            now = self.admission(user["sid"], challenge_id)
            if (
                not isinstance(body, dict)
                or set(body)
                != {"schemaVersion", "actualMap", "gameMode", "practice", "submissionAllowed", "startedAtClient"}
                or type(body.get("schemaVersion")) is not int
                or body["schemaVersion"] != 1
            ):
                raise ApiProblem(400, "malformed_request", "Started schema is invalid.")
            body = {**body, "actualMap": normalize_map(body["actualMap"])}
            try:
                parse_utc(body["startedAtClient"])
            except ValueError:
                raise ApiProblem(422, "malformed_request", "startedAtClient is invalid.") from None
            if body["gameMode"] != "Solo" or body["practice"] is not False or body["submissionAllowed"] is not True:
                raise ApiProblem(422, "challenge_state_conflict", "Started conditions are invalid.")
            with self.db.transaction() as c:
                row = self.owned_challenge(user["sid"], challenge_id, c)
                if body["actualMap"] != map_of(row):
                    raise ApiProblem(422, "replay_mismatch", "Started map differs from the reservation.")
                normalized = dumps(body)
                if row["started_json"] is not None:
                    if normalized != row["started_json"]:
                        raise ApiProblem(
                            409, "challenge_state_conflict", "A different started notification was accepted."
                        )
                    return {
                        "schemaVersion": 1,
                        "challengeId": challenge_id,
                        "status": "started",
                        "startedAt": timestamp(row["started_at"]),
                    }
                if row["status"] != "reserved":
                    raise ApiProblem(409, "challenge_state_conflict", "Challenge cannot be started.")
                c.execute(
                    "UPDATE challenges SET status='started',started_at=?,started_json=? WHERE id=?",
                    (now, normalized, challenge_id),
                )
                self.db.audit(now, user["sid"], "started", challenge_id, request_id, connection=c)
                return {
                    "schemaVersion": 1,
                    "challengeId": challenge_id,
                    "status": "started",
                    "startedAt": timestamp(now),
                }

    def refund(self, c, row, condition, now):
        policy = json.loads(row["policy_json"])
        if row["refunded"] or condition not in policy["refund_conditions"]:
            return False
        return self._apply_refund(c, row, condition, now)

    def _apply_refund(self, c, row, condition, now, actor="system", request_id=None, reason=None):
        """The caller's transaction commits the flag, budget, audit and any result event together."""
        changed = c.execute(
            "UPDATE challenges SET refunded=1,refund_reason=? WHERE id=? AND refunded=0", (condition, row["id"])
        ).rowcount
        if not changed:
            return False
        key = budget_key(row["sid"], row["league_id"], map_of(row))
        budget = c.execute("SELECT used FROM budgets WHERE " + BUDGET_WHERE, key).fetchone()
        if budget is None or budget["used"] < 1:
            raise ApiProblem(503, "storage_unavailable", "Attempt accounting is inconsistent.")
        c.execute(
            "UPDATE budgets SET used=used-1 WHERE " + BUDGET_WHERE,
            key,
        )
        details = {
            "condition": condition,
            "sid": row["sid"],
            "leagueId": row["league_id"],
            "map": map_of(row),
            "usedBefore": budget["used"],
            "usedAfter": budget["used"] - 1,
        }
        if reason is not None:
            details["reason"] = reason
        self.db.audit(
            now, actor, "attempt_refunded", row["id"], request_id, details=details, connection=c
        )
        return True

    @measure_operation()
    def control_challenge(self, challenge_id, action, body, actor, request_id):
        """Caller holds the OS challenge lock, just as for result admission and commit."""
        fields = {"reason", "refundAttempt"} if action == "force-end" else {"reason"}
        if (
            action not in ("force-end", "refund")
            or not isinstance(body, dict)
            or set(body) != fields
            or not isinstance(body.get("reason"), str)
            or not 1 <= len(body["reason"].strip()) <= 500
            or (action == "force-end" and type(body["refundAttempt"]) is not bool)
        ):
            raise ApiProblem(400, "malformed_request", "操作の形式を確認し、理由を1～500文字で入力してください。")
        reason, now = body["reason"].strip(), self.clock()

        def summary(row):
            return {
                "challengeId": row["id"],
                "status": row["status"],
                "abandonedReason": row["abandoned_reason"],
                "attemptRefunded": bool(row["refunded"]),
                "refundReason": row["refund_reason"],
            }

        with self.db.transaction() as c:
            row = c.execute("SELECT * FROM challenges WHERE id=?", (challenge_id,)).fetchone()
            if row is None:
                raise ApiProblem(404, "challenge_not_found", "チャレンジが見つかりません。")
            before = summary(row)
            if action == "force-end":
                # A replay cannot turn an earlier force-end into an additional refund.
                if row["status"] == "abandoned" and row["abandoned_reason"] == "admin_force_ended":
                    return before
                if row["status"] not in ("reserved", "started"):
                    raise ApiProblem(409, "challenge_state_conflict", "終了済みです。最新の状態を確認してください。")
                c.execute(
                    "UPDATE challenges SET status='abandoned',abandoned_reason='admin_force_ended' WHERE id=?",
                    (challenge_id,),
                )
            elif row["status"] not in ("submitted", "abandoned"):
                raise ApiProblem(409, "challenge_state_conflict", "進行中です。強制終了と同時に返却してください。")

            if action == "refund" or body["refundAttempt"]:
                refunded = self._apply_refund(c, row, "admin_manual", now, actor, request_id, reason)
                if refunded and row["status"] == "submitted":
                    result = c.execute("SELECT id FROM results WHERE challenge_id=?", (challenge_id,)).fetchone()
                    self.emit_change(c, result["id"], "attempt_refunded", now)
            after = summary(c.execute("SELECT * FROM challenges WHERE id=?", (challenge_id,)).fetchone())
            if action == "force-end":
                self.db.audit(
                    now, actor, "challenge_force_ended", challenge_id, request_id,
                    {"reason": reason, "sid": row["sid"], "leagueId": row["league_id"], "map": map_of(row),
                     "before": before, "after": after}, c,
                )
            return after

    @measure_operation()
    def result(self, user, challenge_id, metadata, replay, compressed, received, request_id):
        sha = replay.sha256 if replay else None
        digest = canonical_digest({"metadata": metadata, "replaySha256": sha})
        with self.db.transaction() as c:
            row = self.owned_challenge(user["sid"], challenge_id, c)
            self.check_deadline(row, received)
            previous = c.execute("SELECT * FROM results WHERE challenge_id=?", (challenge_id,)).fetchone()
            if previous:
                if previous["digest"] != digest:
                    raise ApiProblem(409, "result_conflict", "A different result was already submitted.")
                return 200, previous["response_json"]
            if c.execute("SELECT 1 FROM results WHERE client_key=?", (metadata["clientResultId"],)).fetchone():
                raise ApiProblem(409, "idempotency_conflict", "This result key belongs to another challenge.")
            if metadata["map"] != map_of(row):
                raise ApiProblem(422, "replay_mismatch", "Result map differs from the reservation.")
            validity = metadata["scoreValidity"]
            ranked = validity["validForRanking"]
            if ranked and replay is None:
                raise ApiProblem(422, "replay_invalid", "A ranking candidate requires a BSOR replay.")
            if replay and validity["invalidReason"] == "replay_unavailable":
                raise ApiProblem(422, "replay_invalid", "replay_unavailable cannot include a replay.")
            if replay:
                platforms = {"steamTicket": {"steam"}, "oculusTicket": {"oculus", "oculuspc"}}
                info = replay.info
                if (
                    info.player_id != user["sid"]
                    or info.platform.lower() not in platforms[row["provider"]]
                    or (info.hash, info.mode, info.difficulty)
                    != (row["map_hash"], row["characteristic"], row["difficulty"])
                ):
                    raise ApiProblem(422, "replay_mismatch", "Replay identity or map differs from the reservation.")
                if ranked and (
                    info.score != metadata["multipliedScore"] or info.game_version != metadata["gameVersion"]
                ):
                    raise ApiProblem(422, "replay_mismatch", "Replay score or game version differs from the result.")
            policy = Policy.parse(json.loads(row["policy_json"]))
            self.check_disk(policy)
            condition = validity["invalidReason"]
            if metadata["endType"] == "preflight_rejected":
                condition = (
                    "preflight_unstarted"
                    if validity["playInstanceCount"] == 0 and row["started_at"] is None
                    else "preflight_started"
                )
            elif metadata["endType"] == "restart":
                condition = "restart"
            if not ranked:
                self.refund(c, row, condition, received)
            budget = c.execute(
                "SELECT * FROM budgets WHERE " + BUDGET_WHERE, budget_key(user["sid"], row["league_id"], map_of(row))
            ).fetchone()
            result_id = str(uuid4())
            response = dumps(
                {
                    "schemaVersion": 1,
                    "submissionId": result_id,
                    "challengeId": challenge_id,
                    "status": "submitted",
                    "validForRanking": ranked,
                    "invalidReason": validity["invalidReason"],
                    "receivedAt": timestamp(received),
                    "replaySha256": sha,
                    "remainingAttempts": max(0, budget["last_limit"] - budget["used"]),
                }
            )
            c.execute(
                "INSERT INTO results(id,challenge_id,client_key,digest,metadata_json,response_json,received_at,"
                "end_type,valid_for_ranking,invalid_reason,modified_score,max_score,replay_sha256) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    result_id,
                    challenge_id,
                    metadata["clientResultId"],
                    digest,
                    dumps(metadata),
                    response,
                    received,
                    metadata["endType"],
                    ranked,
                    validity["invalidReason"],
                    metadata["modifiedScore"],
                    metadata["maxPossibleModifiedScore"],
                    sha,
                ),
            )
            if replay:
                # Replay and receipt commit atomically. SQLite backup includes both.
                c.execute("INSERT INTO replay_blobs VALUES(?,?,?)", (result_id, compressed, replay.byte_count))
            c.execute("UPDATE challenges SET status='submitted',submitted_at=? WHERE id=?", (received, challenge_id))
            self.emit_change(c, result_id, "submitted", received)
            self.db.audit(
                received,
                user["sid"],
                "submitted",
                challenge_id,
                request_id,
                {"submissionId": result_id, "validForRanking": ranked, "invalidReason": validity["invalidReason"]},
                c,
            )
            return 201, response

    def export_result(self, c, result_id):
        r = c.execute(
            "SELECT r.*,c.sid,c.league_id,c.map_hash,c.characteristic,c.difficulty,c.refunded,c.refund_reason "
            "FROM results r JOIN challenges c ON c.id=r.challenge_id WHERE r.id=?",
            (result_id,),
        ).fetchone()
        if r is None:
            raise ApiProblem(404, "submission_not_found", "Submission does not exist.")
        metadata = json.loads(r["metadata_json"])
        return {
            "submissionId": r["id"],
            "challengeId": r["challenge_id"],
            "sid": r["sid"],
            "leagueId": r["league_id"],
            "map": map_of(r),
            "endType": r["end_type"],
            "modifiedScore": r["modified_score"],
            "maxPossibleModifiedScore": r["max_score"],
            "multipliedScore": metadata["multipliedScore"],
            "missedCount": metadata["missedCount"],
            "badCutsCount": metadata["badCutsCount"],
            "goodCutsCount": metadata["goodCutsCount"],
            "accuracyPercent": (100.0 * r["modified_score"] / r["max_score"])
            if r["max_score"] and r["modified_score"] is not None
            else None,
            "validForRanking": bool(r["valid_for_ranking"]),
            "invalidReason": r["invalid_reason"],
            "canceled": bool(r["canceled"]),
            "effectiveForRanking": bool(r["valid_for_ranking"] and not r["canceled"]),
            "moderationVersion": r["moderation_version"],
            "moderationReason": r["moderation_reason"],
            "receivedAt": timestamp(r["received_at"]),
            "replaySha256": r["replay_sha256"],
            "attemptRefunded": bool(r["refunded"]),
            "refundReason": r["refund_reason"],
        }

    def emit_change(self, c, result_id, event, now):
        payload = self.export_result(c, result_id)
        c.execute(
            "INSERT INTO changes(league_id,result_id,event,occurred_at,payload_json) VALUES(?,?,?,?,?)",
            (payload["leagueId"], result_id, event, now, dumps(payload)),
        )

    @measure_operation()
    def moderate(self, result_id, action, version, reason, actor, request_id):
        if (
            action not in ("cancel", "restore")
            or type(version) is not int
            or not isinstance(reason, str)
            or not 1 <= len(reason.strip()) <= 500
        ):
            raise ApiProblem(
                400, "malformed_request", "Action, current version and a reason (1-500 characters) are required."
            )
        now = self.clock()
        with self.db.transaction() as c:
            r = self.export_result(c, result_id)
            desired = action == "cancel"
            if r["moderationVersion"] != version:
                raise ApiProblem(409, "moderation_conflict", "Submission was changed. Refresh before editing.")
            if r["canceled"] == desired:
                return r
            c.execute(
                "UPDATE results SET canceled=?,moderation_version=moderation_version+1,moderation_reason=?,moderated_at=? WHERE id=?",
                (desired, reason.strip(), now, result_id),
            )
            self.emit_change(c, result_id, "canceled" if desired else "restored", now)
            self.db.audit(
                now,
                actor,
                "score_" + action,
                r["challengeId"],
                request_id,
                {"submissionId": result_id, "reason": reason.strip(), "previousVersion": version},
                c,
            )
            return self.export_result(c, result_id)

    @measure_operation()
    def update_policy(self, raw, revision, actor, request_id):
        try:
            policy = Policy.parse(raw)
        except (ValueError, TypeError):
            raise ApiProblem(400, "malformed_request", "設定値が範囲外、または項目が不足しています。") from None
        with self.db.transaction() as c:
            old = c.execute("SELECT * FROM policy WHERE id=1").fetchone()
            if type(revision) is not int or revision != old["revision"]:
                raise ApiProblem(409, "settings_conflict", "設定が変更されています。再読み込みしてください。")
            c.execute("UPDATE policy SET revision=revision+1,value_json=? WHERE id=1", (dumps(asdict(policy)),))
            self.db.audit(
                self.clock(),
                actor,
                "settings_updated",
                request_id=request_id,
                details={"before": json.loads(old["value_json"]), "after": asdict(policy), "revision": revision + 1},
                connection=c,
            )
        return {"revision": revision + 1, "policy": asdict(policy)}

    @measure_operation()
    def sweep(self):
        now = self.clock()
        with self.db.read() as c:
            expired = c.execute(
                "SELECT id FROM challenges WHERE status IN ('reserved','started') AND "
                "(accept_until<? OR (timeout_at IS NOT NULL AND timeout_at<=?)) LIMIT 500",
                (now, now),
            ).fetchall()
        for item in expired:
            lock = self.challenge_lock(item["id"])
            try:
                lock.acquire(timeout=0)
            except ApiProblem:
                continue
            try:
                with self.db.transaction() as c:
                    row = c.execute("SELECT * FROM challenges WHERE id=?", (item["id"],)).fetchone()
                    if row["status"] not in ("reserved", "started"):
                        continue
                    reason = "result_acceptance_expired" if now > row["accept_until"] else "challenge_timed_out"
                    c.execute(
                        "UPDATE challenges SET status='abandoned',abandoned_reason=? WHERE id=?", (reason, row["id"])
                    )
                    self.refund(c, row, "abandoned", now)
                    self.db.audit(now, "system", "abandoned", row["id"], details={"reason": reason}, connection=c)
            finally:
                lock.release()
        with self.db.transaction() as c:
            c.execute("DELETE FROM sessions WHERE expires_at<=?", (now,))
            c.execute("DELETE FROM admin_sessions WHERE expires_at<=?", (now,))
            c.execute("DELETE FROM replay_viewer_tokens WHERE expires_at<=?", (now,))
            c.execute("DELETE FROM rate_limits WHERE window<?", (int(now // 60) - 2,))

import json
import shutil

from . import replay_viewer
from .contracts import require_uuid
from .errors import ApiProblem
from .service import map_of, timestamp


def integer_query(query, name, default=0, maximum=2147483647):
    raw = query.get(name, str(default))
    if not isinstance(raw, str) or not raw.isascii() or not raw.isdecimal() or len(raw) > 18 or int(raw) > maximum:
        raise ApiProblem(400, "malformed_request", f"{name} must be a nonnegative decimal integer.")
    return int(raw)


def filters(query, alias="c"):
    clauses, args = [], []
    if "sid" in query:
        sid = query["sid"]
        if not 1 <= len(sid) <= 128:
            raise ApiProblem(400, "malformed_request", "sid is invalid.")
        clauses.append(f"{alias}.sid=?")
        args.append(sid)
    if "leagueId" in query:
        league_id = integer_query(query, "leagueId")
        if not league_id:
            raise ApiProblem(400, "malformed_request", "leagueId must be positive.")
        clauses.append(f"{alias}.league_id=?")
        args.append(league_id)
    return clauses, args


def dashboard(service):
    with service.db.read() as c:
        counts = {
            name: c.execute("SELECT COUNT(*) FROM challenges WHERE status=?", (name,)).fetchone()[0]
            for name in ("reserved", "started", "submitted", "abandoned")
        }
        counts["users"] = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        counts["ranked"] = c.execute(
            "SELECT COUNT(*) FROM results WHERE valid_for_ranking=1 AND canceled=0"
        ).fetchone()[0]
        counts["canceled"] = c.execute("SELECT COUNT(*) FROM results WHERE canceled=1").fetchone()[0]
        cache = [
            {"leagueId": r["league_id"], "fetchedAt": timestamp(r["fetched_at"]), "lastError": r["last_error"]}
            for r in c.execute("SELECT league_id,fetched_at,last_error FROM league_cache ORDER BY league_id LIMIT 100")
        ]
        maintenance = {r["name"]: r["value"] for r in c.execute("SELECT * FROM maintenance")}
        tokens = [
            {"name": r["name"], "createdAt": timestamp(r["created_at"]), "revoked": r["revoked_at"] is not None}
            for r in c.execute("SELECT name,created_at,revoked_at FROM service_tokens")
        ]
    disk = shutil.disk_usage(service.config.data_dir)
    return {
        "serverTime": timestamp(service.clock()),
        "counts": counts,
        "cache": cache,
        "diskFreeMb": disk.free // (1024 * 1024),
        "databaseMb": round(service.db.path.stat().st_size / (1024 * 1024), 2),
        "maintenance": maintenance,
        "serviceTokens": tokens,
        "authentication": {
            "steamConfigured": bool(service.config.steam_api_key),
            "oculusEnabled": service.config.oculus_enabled,
        },
    }


def challenges(service, query):
    clauses, args = filters(query)
    cursor, limit = integer_query(query, "before", maximum=9223372036854775807), integer_query(query, "limit", 50, 200)
    if limit == 0:
        raise ApiProblem(400, "malformed_request", "limit must be positive.")
    if cursor:
        clauses.append("c.rowid<?")
        args.append(cursor)
    state = query.get("status")
    if state:
        if state not in ("reserved", "started", "submitted", "abandoned"):
            raise ApiProblem(400, "malformed_request", "Invalid challenge status.")
        clauses.append("c.status=?")
        args.append(state)
    where = " AND ".join(clauses) or "1=1"
    with service.db.read() as c:
        rows = c.execute(
            "SELECT c.rowid AS cursor,c.*,r.id AS submission_id,r.valid_for_ranking,r.canceled,r.end_type,r.modified_score "
            "FROM challenges c LEFT JOIN results r ON r.challenge_id=c.id WHERE "
            + where
            + " ORDER BY c.rowid DESC LIMIT ?",
            (*args, limit + 1),
        ).fetchall()
    items = [
        {
            "challengeId": r["id"],
            "sid": r["sid"],
            "leagueId": r["league_id"],
            "map": map_of(r),
            "status": r["status"],
            "abandonedReason": r["abandoned_reason"],
            "attemptNumber": r["attempt_number"],
            "attemptLimit": r["attempt_limit"],
            "reservedAt": timestamp(r["reserved_at"]),
            "startedAt": timestamp(r["started_at"]),
            "resultAcceptUntil": timestamp(r["accept_until"]),
            "timeoutAt": timestamp(r["timeout_at"]),
            "attemptRefunded": bool(r["refunded"]),
            "refundReason": r["refund_reason"],
            "submissionId": r["submission_id"],
            "endType": r["end_type"],
            "modifiedScore": r["modified_score"],
            "validForRanking": bool(r["valid_for_ranking"]),
            "canceled": bool(r["canceled"]),
        }
        for r in rows[:limit]
    ]
    return {"items": items, "nextCursor": rows[limit - 1]["cursor"] if len(rows) > limit else None}


def users(service, query):
    q = query.get("q", "")
    if len(q) > 128:
        raise ApiProblem(400, "malformed_request", "Search is too long.")
    after = query.get("after", "")
    limit = max(1, integer_query(query, "limit", 50, 200))
    with service.db.read() as c:
        rows = c.execute(
            "SELECT u.*, (SELECT COUNT(*) FROM challenges WHERE sid=u.sid) AS challenges, "
            "(SELECT COUNT(*) FROM challenges ch JOIN results r ON r.challenge_id=ch.id WHERE ch.sid=u.sid) AS submissions "
            "FROM users u WHERE u.sid>? AND (instr(u.sid,?)>0 OR instr(u.display_name,?)>0) ORDER BY u.sid LIMIT ?",
            (after, q, q, limit + 1),
        ).fetchall()
    return {
        "items": [
            {
                "sid": r["sid"],
                "displayName": r["display_name"],
                "challenges": r["challenges"],
                "submissions": r["submissions"],
            }
            for r in rows[:limit]
        ],
        "nextCursor": rows[limit - 1]["sid"] if len(rows) > limit else None,
    }


def user_budgets(service, sid):
    with service.db.read() as c:
        rows = c.execute(
            "SELECT * FROM budgets WHERE sid=? ORDER BY league_id,map_hash,characteristic,difficulty", (sid,)
        ).fetchall()
        caches = {r["league_id"]: json.loads(r["projection_json"]) for r in c.execute("SELECT * FROM league_cache")}
    items = []
    for r in rows:
        projection = caches.get(r["league_id"])
        key = map_of(r)
        found = (
            next((m for m in projection["maps"] if all(m[k] == v for k, v in key.items())), None)
            if projection
            else None
        )
        limit = found["qualifier_attempt_limit"] if found else None
        items.append(
            {
                "leagueId": r["league_id"],
                "map": key,
                "usedAttempts": r["used"],
                "totalChallenges": r["total"],
                "refundedAttempts": r["total"] - r["used"],
                "attemptLimit": limit,
                "remainingAttempts": max(0, limit - r["used"]) if limit is not None else None,
            }
        )
    return {"items": items, "limitSource": "last validated JBSL-WEB cache"}


def audit(service, query):
    before = integer_query(query, "before", maximum=9223372036854775807)
    limit = max(1, integer_query(query, "limit", 50, 200))
    clauses, args = [], []
    if before:
        clauses.append("id<?")
        args.append(before)
    for query_name, column in (("challengeId", "challenge_id"), ("actor", "actor")):
        if query_name in query:
            clauses.append(column + "=?")
            args.append(query[query_name])
    with service.db.read() as c:
        rows = c.execute(
            "SELECT * FROM audit WHERE " + (" AND ".join(clauses) or "1=1") + " ORDER BY id DESC LIMIT ?",
            (*args, limit + 1),
        ).fetchall()
    items = []
    for r in rows[:limit]:
        details = json.loads(r["details_json"])
        items.append({
            "id": r["id"],
            "occurredAt": timestamp(r["occurred_at"]),
            "actor": r["actor"],
            "event": r["event"],
            "challengeId": r["challenge_id"],
            "requestId": r["request_id"],
            "details": details,
            "elapsedMs": details.get("elapsedMs"),
        })
    return {
        "items": items,
        "nextCursor": rows[limit - 1]["id"] if len(rows) > limit else None,
    }


def changes(service, query):
    after = integer_query(query, "after", maximum=9223372036854775807)
    limit = max(1, integer_query(query, "limit", 100, 500))
    league_id = integer_query(query, "leagueId") if "leagueId" in query else None
    with service.db.read() as c:
        c.execute("BEGIN")
        high = c.execute("SELECT COALESCE(MAX(seq),0) FROM changes").fetchone()[0]
        sql, args = "SELECT * FROM changes WHERE seq>?", [after]
        if league_id is not None:
            if not league_id:
                raise ApiProblem(400, "malformed_request", "leagueId must be positive.")
            sql += " AND league_id=?"
            args.append(league_id)
        rows = c.execute(sql + " ORDER BY seq LIMIT ?", (*args, limit + 1)).fetchall()
        items = [
            {
                "seq": r["seq"],
                "event": r["event"],
                "occurredAt": timestamp(r["occurred_at"]),
                "submission": json.loads(r["payload_json"]),
            }
            for r in rows[:limit]
        ]
    return {
        "schemaVersion": 1,
        "items": items,
        "nextCursor": items[-1]["seq"] if len(rows) > limit else max(high, after),
        "hasMore": len(rows) > limit,
        "highWatermark": high,
    }


def leaderboard_rows(c, league_id):
    return c.execute(
        "WITH best AS (SELECT r.id,c.sid,c.map_hash,c.characteristic,c.difficulty,r.modified_score, "
        "ROW_NUMBER() OVER(PARTITION BY c.sid,c.map_hash,c.characteristic,c.difficulty "
        "ORDER BY r.modified_score DESC,r.received_at,r.id) AS choice "
        "FROM results r JOIN challenges c ON c.id=r.challenge_id "
        "WHERE c.league_id=? AND r.valid_for_ranking=1 AND r.canceled=0) "
        "SELECT id,u.display_name,EXISTS(SELECT 1 FROM replay_blobs WHERE result_id=best.id) AS has_replay,"
        "RANK() OVER(PARTITION BY map_hash,characteristic,difficulty ORDER BY modified_score DESC) AS rank "
        "FROM best JOIN users u ON u.sid=best.sid WHERE choice=1 "
        "ORDER BY map_hash,characteristic,difficulty,modified_score DESC,best.sid",
        (league_id,),
    ).fetchall()


def leaderboard(service, league_id):
    with service.db.read() as c:
        c.execute("BEGIN")
        items = [{**service.export_result(c, r["id"]), "rank": r["rank"]} for r in leaderboard_rows(c, league_id)]
    return {"schemaVersion": 1, "leagueId": league_id, "items": items}


def rankings(service, query, *, public_replays=False):
    league_id = integer_query(query, "leagueId") if "leagueId" in query else None
    if league_id == 0:
        raise ApiProblem(400, "malformed_request", "leagueId must be positive.")
    with service.db.read() as c:
        # Keep ranks, selected submissions and their moderation state in one read snapshot.
        c.execute("BEGIN")
        leagues = [
            {"leagueId": r["league_id"], "title": r["title"] or f"League {r['league_id']}"}
            for r in c.execute(
                "SELECT l.league_id,json_extract(cache.projection_json,'$.league_title') AS title "
                "FROM (SELECT league_id FROM league_cache UNION SELECT league_id FROM challenges) l "
                "LEFT JOIN league_cache cache ON cache.league_id=l.league_id ORDER BY l.league_id"
            )
        ]
        if league_id is None and leagues:
            league_id = leagues[0]["leagueId"]
        if league_id is not None and not any(league["leagueId"] == league_id for league in leagues):
            raise ApiProblem(404, "league_not_found", "このサーバに記録されたリーグではありません。")

        def key(m):
            return m["hash"], m["characteristic"], m["difficulty"]

        cache = c.execute("SELECT projection_json FROM league_cache WHERE league_id=?", (league_id,)).fetchone()
        maps = {}
        if cache:
            for m in json.loads(cache["projection_json"])["maps"]:
                maps[key(m)] = {
                    **{field: m[field] for field in ("hash", "characteristic", "difficulty")},
                    "title": m.get("title") or m["hash"],
                    "attemptLimit": m["qualifier_attempt_limit"],
                    "songDurationSeconds": m["song_duration_seconds"],
                }
        # Historical charts remain accessible even after the upstream playlist changes.
        for r in c.execute(
            "SELECT DISTINCT map_hash,characteristic,difficulty FROM challenges WHERE league_id=? "
            "ORDER BY map_hash,characteristic,difficulty",
            (league_id,),
        ):
            m = map_of(r)
            maps.setdefault(key(m), {**m, "title": m["hash"], "attemptLimit": None, "songDurationSeconds": None})
        budgets = {
            (r["sid"], key(map_of(r))): r["used"]
            for r in c.execute("SELECT * FROM budgets WHERE league_id=?", (league_id,))
        }
        items = []
        for r in leaderboard_rows(c, league_id):
            item = {**service.export_result(c, r["id"]), "rank": r["rank"], "displayName": r["display_name"]}
            map_key = key(item["map"])
            limit = maps[map_key]["attemptLimit"]
            used = budgets.get((item["sid"], map_key))
            item["remainingAttempts"] = max(0, limit - used) if limit is not None and used is not None else None
            if public_replays:
                item["replay"] = replay_viewer.public_links(service, r["id"], item["sid"], r["has_replay"])
            items.append(item)
    return {"leagues": leagues, "leagueId": league_id, "maps": list(maps.values()), "items": items}


def public_rankings(service, query):
    data = rankings(service, query, public_replays=True)
    map_fields = ("hash", "characteristic", "difficulty")
    item_fields = (
        "rank", "sid", "displayName", "modifiedScore", "accuracyPercent", "remainingAttempts", "receivedAt", "endType",
    )
    # Explicitly project every level so future admin-only fields cannot become public.
    return {
        "leagues": [{field: league[field] for field in ("leagueId", "title")} for league in data["leagues"]],
        "leagueId": data["leagueId"],
        "maps": [
            {field: chart[field] for field in (*map_fields, "title", "attemptLimit", "songDurationSeconds")}
            for chart in data["maps"]
        ],
        "items": [
            {
                **{field: item[field] for field in item_fields},
                "map": {field: item["map"][field] for field in map_fields},
                "replay": {field: item["replay"][field] for field in ("downloadUrl", "beatleaderUrl", "arcviewerUrl")},
            }
            for item in data["items"]
        ],
    }


def public_replay(service, submission_id, player_id=None, *, metadata_only=False):
    submission_id = require_uuid(submission_id, "submissionId")
    with service.db.read() as c:
        # A moderation or best-score change cannot split eligibility from the blob read.
        c.execute("BEGIN")
        row = c.execute(
            "SELECT ch.league_id,ch.sid FROM results r JOIN challenges ch ON ch.id=r.challenge_id WHERE r.id=?",
            (submission_id,),
        ).fetchone()
        if row is None or (player_id is not None and row["sid"] != player_id) or not any(
            best["id"] == submission_id and best["has_replay"] for best in leaderboard_rows(c, row["league_id"])
        ):
            raise ApiProblem(404, "replay_not_found", "このReplayは現在の公開ランキングにありません。ページを再読み込みしてください。")
        if not metadata_only:
            return c.execute("SELECT gzip_data FROM replay_blobs WHERE result_id=?", (submission_id,)).fetchone()[0]

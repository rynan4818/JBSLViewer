from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from .errors import ApiProblem


HASH_RE = re.compile(r"^[0-9A-F]{40}$")
SID_RE = re.compile(r"^\S+$")
DIFFICULTIES = {"Easy", "Normal", "Hard", "Expert", "ExpertPlus"}


def parse_utc(value: str | None, *, nullable: bool = False) -> datetime | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise ValueError("datetime must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("datetime must include an offset")
    return parsed.astimezone(timezone.utc)


def utc_text(value: datetime) -> str:
    value = value.astimezone(timezone.utc)
    text = value.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return text


def require_uuid(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ApiProblem(400, "malformed_request", f"{field} must be a UUID string.")
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise ApiProblem(400, "malformed_request", f"{field} must be a UUID string.") from exc


def normalize_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"hash", "characteristic", "difficulty"}:
        raise ApiProblem(422, "map_not_found", "MapKey must contain hash, characteristic and difficulty.")
    raw_hash = value.get("hash")
    characteristic = value.get("characteristic")
    difficulty = value.get("difficulty")
    if not all(isinstance(v, str) for v in (raw_hash, characteristic, difficulty)):
        raise ApiProblem(422, "map_not_found", "MapKey values must be strings.")
    normalized_hash = raw_hash.strip().upper()
    normalized_difficulty = {"Expert+": "ExpertPlus", "Expert Plus": "ExpertPlus"}.get(difficulty, difficulty)
    if not HASH_RE.fullmatch(normalized_hash) or not characteristic or normalized_difficulty not in DIFFICULTIES:
        raise ApiProblem(422, "map_not_found", "MapKey is invalid.")
    return {"hash": normalized_hash, "characteristic": characteristic, "difficulty": normalized_difficulty}


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def require_positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ApiProblem(400, "malformed_request", f"{field} must be a positive JSON integer.")
    return value


def validate_projection(data: Any) -> dict[str, Any]:
    try:
        if not isinstance(data, dict):
            raise ValueError("root")
        league_id = data["league_id"]
        if isinstance(league_id, bool) or not isinstance(league_id, int) or league_id <= 0:
            raise ValueError("league_id")
        if not isinstance(data.get("league_title"), str):
            raise ValueError("league_title")
        for key in ("isLive", "isOpen"):
            if type(data[key]) is not bool:
                raise ValueError(key)
        parse_utc(data["end"])
        qualifier = data["qualifier"]
        required_q = {"enabled", "submission_method", "revision", "starts_at", "ends_at"}
        if not isinstance(qualifier, dict) or not required_q.issubset(qualifier):
            raise ValueError("qualifier")
        if type(qualifier["enabled"]) is not bool or not isinstance(qualifier["submission_method"], str) or not isinstance(qualifier["revision"], str):
            raise ValueError("qualifier values")
        starts_at = parse_utc(qualifier["starts_at"], nullable=True)
        ends_at = parse_utc(qualifier["ends_at"], nullable=True)
        effective_end = ends_at or parse_utc(data["end"])
        if starts_at is not None and starts_at > effective_end:
            raise ValueError("qualifier window")
        participants = data["participants"]
        if not isinstance(participants, list):
            raise ValueError("participants")
        sids = []
        for participant in participants:
            if not isinstance(participant, dict) or set(participant) != {"sid"} or not isinstance(participant["sid"], str) or not SID_RE.fullmatch(participant["sid"]):
                raise ValueError("participant")
            sids.append(participant["sid"])
        if len(sids) != len(set(sids)):
            raise ValueError("duplicate sid")
        maps = data["maps"]
        if not isinstance(maps, list):
            raise ValueError("maps")
        keys: set[tuple[str, str, str]] = set()
        projected_maps = []
        for item in maps:
            normalized = normalize_map({k: item[k] for k in ("hash", "characteristic", "difficulty")})
            key = tuple(normalized.values())
            if key in keys:
                raise ValueError("duplicate MapKey")
            keys.add(key)
            limit = item["qualifier_attempt_limit"]
            if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100):
                raise ValueError("attempt limit")
            duration = item["song_duration_seconds"]
            if duration is not None and (isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0):
                raise ValueError("duration")
            projected_maps.append({**normalized, "title": item.get("title"), "song_duration_seconds": duration, "qualifier_attempt_limit": limit})
        if qualifier["enabled"] and any(m["qualifier_attempt_limit"] is None for m in projected_maps):
            raise ValueError("enabled qualifier map without limit")
        if not qualifier["enabled"] and any(m["qualifier_attempt_limit"] is not None for m in projected_maps):
            raise ValueError("disabled qualifier map with limit")
        return {
            "league_id": league_id,
            "league_title": data.get("league_title"),
            "isLive": data["isLive"],
            "isOpen": data["isOpen"],
            "end": data["end"],
            "qualifier": {k: qualifier[k] for k in required_q},
            "participants": [{"sid": sid} for sid in sids],
            "maps": projected_maps,
        }
    except ApiProblem as exc:
        raise ValueError(exc.message) from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid leaderboard projection: {exc}") from exc

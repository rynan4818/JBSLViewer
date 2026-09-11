from __future__ import annotations
from typing import Any
from .errors import ApiProblem
from .contracts import normalize_map, parse_utc, require_uuid


def validate_metadata(metadata, path_id, key):
    try:
        result = _validate_result_metadata(metadata, path_id, key)
        for field in (
            "multipliedScore",
            "modifiedScore",
            "maxPossibleModifiedScore",
            "missedCount",
            "badCutsCount",
            "goodCutsCount",
            "maxCombo",
        ):
            value = result[field]
            if value is not None and value > 2147483647:
                raise ValueError("score exceeds the game's int32 range")
        if result["scoreValidity"]["validForRanking"]:
            if any(result[k] is None for k in ("multipliedScore", "modifiedScore", "maxPossibleModifiedScore")):
                raise ValueError("ranked score fields are required")
            if result["modifiedScore"] > result["maxPossibleModifiedScore"]:
                raise ValueError("score exceeds maximum")
        result["clientResultId"] = require_uuid(result["clientResultId"], "clientResultId")
        result["challengeId"] = require_uuid(result["challengeId"], "challengeId")
        return result
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise ApiProblem(422, "malformed_request", "Result metadata contains invalid values.") from None


REQUIRED_RESULT_KEYS = {
    "schemaVersion",
    "clientResultId",
    "challengeId",
    "map",
    "endState",
    "endAction",
    "endType",
    "endSongTime",
    "multipliedScore",
    "modifiedScore",
    "maxPossibleModifiedScore",
    "missedCount",
    "badCutsCount",
    "goodCutsCount",
    "maxCombo",
    "fullCombo",
    "energy",
    "modifiers",
    "submissionEligibility",
    "scoreValidity",
    "timing",
    "clientVersion",
    "gameVersion",
}


def _validate_result_metadata(metadata: Any, path_id: str, key: str) -> dict[str, Any]:
    if (
        not isinstance(metadata, dict)
        or not REQUIRED_RESULT_KEYS.issubset(metadata)
        or not set(metadata).issubset(REQUIRED_RESULT_KEYS | {"diagnostics"})
        or type(metadata.get("schemaVersion")) is not int
        or metadata.get("schemaVersion") != 1
    ):
        raise ApiProblem(400, "malformed_request", "Result metadata is incomplete.")
    if (
        require_uuid(metadata["clientResultId"], "clientResultId") != key
        or require_uuid(metadata["challengeId"], "challengeId") != path_id
    ):
        raise ApiProblem(409, "idempotency_conflict", "Result identifiers do not match the request.")
    metadata = dict(metadata)
    metadata["map"] = normalize_map(metadata["map"])
    if (
        metadata["endState"] not in {"cleared", "failed", "incomplete", "unknown"}
        or metadata["endAction"] not in {"none", "quit", "restart", "unknown"}
        or metadata["endType"] not in {"clear", "fail", "quit", "restart", "unknown", "preflight_rejected"}
    ):
        raise ApiProblem(422, "malformed_request", "Result ending fields are invalid.")
    for field in ("endSongTime", "energy"):
        value = metadata[field]
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or value != value
            or value in (float("inf"), float("-inf"))
            or (field == "endSongTime" and value < 0)
        ):
            raise ApiProblem(422, "malformed_request", f"{field} is invalid.")
    for field in (
        "multipliedScore",
        "modifiedScore",
        "maxPossibleModifiedScore",
        "missedCount",
        "badCutsCount",
        "goodCutsCount",
        "maxCombo",
    ):
        value = metadata[field]
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise ApiProblem(422, "malformed_request", f"{field} is invalid.")
    if metadata["fullCombo"] is not None and type(metadata["fullCombo"]) is not bool:
        raise ApiProblem(422, "malformed_request", "fullCombo is invalid.")
    if metadata["modifiers"] is not None and (
        not isinstance(metadata["modifiers"], list)
        or any(not isinstance(value, str) for value in metadata["modifiers"])
    ):
        raise ApiProblem(422, "malformed_request", "modifiers is invalid.")
    if (
        not isinstance(metadata["clientVersion"], str)
        or not metadata["clientVersion"]
        or not isinstance(metadata["gameVersion"], str)
        or not metadata["gameVersion"]
    ):
        raise ApiProblem(422, "malformed_request", "Client version fields are invalid.")
    eligibility = metadata["submissionEligibility"]
    validity = metadata["scoreValidity"]
    if (
        not isinstance(eligibility, dict)
        or set(eligibility) != {"allowedAtStart", "remainedAllowed", "blockers"}
        or type(eligibility.get("allowedAtStart")) is not bool
        or type(eligibility.get("remainedAllowed")) is not bool
        or not isinstance(eligibility.get("blockers"), list)
        or any(not isinstance(value, str) for value in eligibility.get("blockers", []))
    ):
        raise ApiProblem(422, "malformed_request", "submissionEligibility is invalid.")
    if (
        not isinstance(validity, dict)
        or set(validity) != {"validForRanking", "invalidReason", "restartDetected", "playInstanceCount"}
        or type(validity.get("validForRanking")) is not bool
        or type(validity.get("restartDetected")) is not bool
        or isinstance(validity.get("playInstanceCount"), bool)
        or not isinstance(validity.get("playInstanceCount"), int)
        or not 0 <= validity["playInstanceCount"] <= 1
    ):
        raise ApiProblem(422, "malformed_request", "scoreValidity is invalid.")
    if eligibility["remainedAllowed"] and not eligibility["allowedAtStart"]:
        raise ApiProblem(422, "malformed_request", "remainedAllowed requires allowedAtStart.")
    reasons = {None, "quit", "restarted", "unknown", "preflight_rejected", "submission_disabled", "replay_unavailable"}
    if validity.get("invalidReason") not in reasons:
        raise ApiProblem(422, "malformed_request", "invalidReason is invalid.")
    ending_contract = {
        "clear": ("cleared", "none"),
        "fail": ("failed", "none"),
        "quit": ("incomplete", "quit"),
        "restart": ("incomplete", "restart"),
        "unknown": ("unknown", "unknown"),
        "preflight_rejected": ("incomplete", "none"),
    }
    if (metadata["endState"], metadata["endAction"]) != ending_contract[metadata["endType"]]:
        raise ApiProblem(422, "malformed_request", "End state/action/type combination is invalid.")
    forced_invalid = (
        metadata["endType"] in {"quit", "restart", "unknown", "preflight_rejected"}
        or metadata["endAction"] == "restart"
        or validity["restartDetected"]
        or validity["playInstanceCount"] != 1
        or not eligibility["allowedAtStart"]
        or not eligibility["remainedAllowed"]
    )
    if forced_invalid and validity["validForRanking"]:
        raise ApiProblem(422, "malformed_request", "This result cannot be ranked.")
    expected_reason = {
        "quit": "quit",
        "restart": "restarted",
        "unknown": "unknown",
        "preflight_rejected": "preflight_rejected",
    }.get(metadata["endType"])
    if expected_reason is None and (not eligibility["allowedAtStart"] or not eligibility["remainedAllowed"]):
        expected_reason = "submission_disabled"
    if validity["validForRanking"] and validity["invalidReason"] is not None:
        raise ApiProblem(422, "malformed_request", "A ranking result cannot declare an invalid reason.")
    if expected_reason is not None and validity["invalidReason"] != expected_reason:
        raise ApiProblem(422, "malformed_request", "invalidReason does not follow the ending priority contract.")
    if (
        metadata["endType"] in {"clear", "fail"}
        and not validity["validForRanking"]
        and expected_reason is None
        and validity["invalidReason"] != "replay_unavailable"
    ):
        raise ApiProblem(422, "malformed_request", "An unranked clear/fail must identify replay_unavailable.")
    if metadata["endType"] == "restart" and (not validity["restartDetected"] or validity["playInstanceCount"] != 1):
        raise ApiProblem(422, "malformed_request", "Restart metadata is inconsistent.")
    timing = metadata["timing"]
    timing_keys = {
        "confirmedAtClient",
        "reserveResponseReceivedAtClient",
        "startedAtClient",
        "endedAtClient",
        "resultFinalizedAtClient",
        "localSongDurationSeconds",
        "songSpeedMultiplier",
        "totalPauseSeconds",
    }
    if not isinstance(timing, dict) or set(timing) != timing_keys:
        raise ApiProblem(422, "malformed_request", "timing is incomplete.")
    for field in (
        "confirmedAtClient",
        "reserveResponseReceivedAtClient",
        "startedAtClient",
        "endedAtClient",
        "resultFinalizedAtClient",
    ):
        if timing[field] is not None:
            try:
                parse_utc(timing[field])
            except (TypeError, ValueError) as exc:
                raise ApiProblem(422, "malformed_request", f"{field} is invalid.") from exc
    for field in ("localSongDurationSeconds", "songSpeedMultiplier", "totalPauseSeconds"):
        value = timing[field]
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or value != value
            or value in (float("inf"), float("-inf"))
            or value < 0
            or (field != "totalPauseSeconds" and value == 0)
        ):
            raise ApiProblem(422, "malformed_request", f"{field} is invalid.")
    if metadata["endType"] == "preflight_rejected":
        if validity["playInstanceCount"] not in {0, 1}:
            raise ApiProblem(
                422, "malformed_request", "preflight_rejected playInstanceCount must describe the observed play."
            )
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
        if (
            diagnostics.get("replayGenerationFailed") is not None
            and type(diagnostics.get("replayGenerationFailed")) is not bool
        ):
            raise ApiProblem(422, "malformed_request", "diagnostics.replayGenerationFailed is invalid.")
        if diagnostics.get("actualMap") is not None:
            diagnostics = dict(diagnostics)
            diagnostics["actualMap"] = normalize_map(diagnostics["actualMap"])
            metadata["diagnostics"] = diagnostics
    return metadata

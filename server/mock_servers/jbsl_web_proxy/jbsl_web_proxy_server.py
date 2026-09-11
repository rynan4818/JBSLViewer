from __future__ import annotations

import copy
import json
import logging
import math
import os
import re
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from .config import Settings, prepare_http_scope, require_loopback_bind
from .errors import ApiProblem, problem_response
from .schemas import parse_utc, validate_projection
from .scoresaber import ScoreSaber, total_rank_names


LOG = logging.getLogger("jbsl_mock.web_proxy")
LEAGUE_PATH = re.compile(r"^[1-9][0-9]*$")


class FixtureStore:
    def __init__(self, path: Path):
        self.path = path
        raw = json.loads(path.read_text(encoding="utf-8"))
        if type(raw.get("schemaVersion")) is not int or raw.get("schemaVersion") != 1 or not isinstance(raw.get("leagues"), dict):
            raise ValueError("fixture schemaVersion/leagues is invalid")
        self.leagues = raw["leagues"]
        for league_text, fixture in self.leagues.items():
            self._validate(league_text, fixture)

    @staticmethod
    def _validate(league_text: str, fixture: Any) -> None:
        if not LEAGUE_PATH.fullmatch(league_text) or not isinstance(fixture, dict):
            raise ValueError(f"invalid fixture league key {league_text!r}")
        required = {"isLive", "isOpen", "end", "participants", "qualifier", "maps"}
        if not required.issubset(fixture):
            raise ValueError(f"fixture league {league_text} lacks {sorted(required - set(fixture))}")
        if type(fixture["isLive"]) is not bool or type(fixture["isOpen"]) is not bool:
            raise ValueError(f"fixture league {league_text} has invalid state")
        if type(fixture.get("auto_add_ranking_sids", True)) is not bool:
            raise ValueError(f"fixture league {league_text} has invalid auto_add_ranking_sids")
        parse_utc(fixture["end"])
        q = fixture["qualifier"]
        q_required = {"enabled", "submission_method", "revision", "starts_at", "ends_at"}
        if not isinstance(q, dict) or not q_required.issubset(q) or type(q["enabled"]) is not bool or not isinstance(q["submission_method"], str) or not isinstance(q["revision"], str):
            raise ValueError(f"fixture league {league_text} has invalid qualifier")
        parse_utc(q["starts_at"], nullable=True)
        parse_utc(q["ends_at"], nullable=True)
        sids = []
        for p in fixture["participants"]:
            if not isinstance(p, dict) or set(p) != {"sid"} or not isinstance(p["sid"], str) or not p["sid"] or p["sid"].strip() != p["sid"]:
                raise ValueError(f"fixture league {league_text} has invalid participant")
            sids.append(p["sid"])
        if len(sids) != len(set(sids)):
            raise ValueError(f"fixture league {league_text} has duplicate sid")
        selectors = set()
        for m in fixture["maps"]:
            required_map = {"characteristic", "difficulty", "song_duration_seconds", "qualifier_attempt_limit"}
            if not isinstance(m, dict) or not required_map.issubset(m) or (("lid" in m) == ("index" in m)):
                raise ValueError(f"fixture league {league_text} has invalid map selector/fields")
            selector = ("lid", str(m["lid"])) if "lid" in m else ("index", m["index"])
            if selector in selectors:
                raise ValueError(f"fixture league {league_text} has duplicate map selector")
            selectors.add(selector)
            limit = m["qualifier_attempt_limit"]
            duration = m["song_duration_seconds"]
            if not isinstance(m["characteristic"], str) or not m["characteristic"] or m["difficulty"] not in {"Easy", "Normal", "Hard", "Expert", "ExpertPlus"}:
                raise ValueError(f"fixture league {league_text} has invalid MapKey fields")
            if duration is not None and (isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0):
                raise ValueError(f"fixture league {league_text} has invalid duration")
            if q["enabled"]:
                if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
                    raise ValueError(f"fixture league {league_text} has invalid attempt limit")
            elif limit is not None:
                raise ValueError(f"non-qualifier league {league_text} must use null limits")
        if not q["enabled"] and q["submission_method"] != "external_leaderboard":
            raise ValueError(f"non-qualifier league {league_text} must use external_leaderboard")

    def get(self, league_id: int) -> dict[str, Any] | None:
        return self.leagues.get(str(league_id))


def ranking_sids(upstream: dict[str, Any]) -> list[str]:
    """Collect exact string SIDs in ranking order, including map-only scores."""
    rankings = [upstream.get("total_rank")]
    maps = upstream.get("maps")
    if isinstance(maps, list):
        rankings.extend(item.get("scores") for item in maps if isinstance(item, dict))
    sids = dict.fromkeys(
        row["sid"]
        for ranking in rankings if isinstance(ranking, list)
        for row in ranking if isinstance(row, dict)
        if isinstance(row.get("sid"), str) and re.fullmatch(r"\S+", row["sid"])
    )
    return list(sids)


def merge_leaderboard(upstream: Any, fixture: dict[str, Any], league_id: int) -> dict[str, Any]:
    if (not isinstance(upstream, dict) or upstream.get("league_id") != league_id
            or not isinstance(upstream.get("maps"), list) or any(not isinstance(m, dict) for m in upstream["maps"])):
        raise ApiProblem(502, "upstream_invalid", "The upstream leaderboard response is invalid.")
    result = json.loads(json.dumps(upstream))
    result.update(copy.deepcopy({key: fixture[key] for key in ("isLive", "isOpen", "end", "participants", "qualifier")}))
    if fixture.get("auto_add_ranking_sids", True):
        seen = {p["sid"] for p in result["participants"]}
        result["participants"].extend({"sid": sid} for sid in ranking_sids(upstream) if sid not in seen)
    names = total_rank_names(upstream)
    for participant in result["participants"]:
        participant["name"] = names.get(participant["sid"], participant["sid"])
    used: set[int] = set()
    for patch in fixture["maps"]:
        if "lid" in patch:
            matches = [i for i, item in enumerate(result["maps"]) if str(item.get("lid")) == str(patch["lid"])]
        else:
            matches = [patch["index"]] if isinstance(patch["index"], int) and 0 <= patch["index"] < len(result["maps"]) else []
        if len(matches) != 1 or matches[0] in used:
            raise ApiProblem(409, "mock_fixture_invalid", "Fixture map selection is missing or ambiguous.", details={"leagueId": league_id})
        index = matches[0]
        used.add(index)
        for key in ("characteristic", "difficulty", "song_duration_seconds", "qualifier_attempt_limit"):
            result["maps"][index][key] = patch[key]
    if len(used) != len(result["maps"]):
        raise ApiProblem(409, "mock_fixture_invalid", "Every upstream map must have one fixture mapping.", details={"leagueId": league_id})
    try:
        validate_projection(result)
    except ValueError as exc:
        raise ApiProblem(409, "mock_fixture_invalid", "The merged fixture is invalid.", details={"leagueId": league_id}) from exc
    return result


def create_app(settings: Settings | None = None, *, control=None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.validate()
    fixtures = FixtureStore(settings.fixture_path)
    app = FastAPI(title="JBSL-WEB Qualifier Proxy (TEST ONLY / 本番利用禁止)", version="1", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.fixtures = fixtures
    app.state.scoresaber = control.scoresaber if control is not None else ScoreSaber()
    app.state.counts = {"leaderboard": 0, "byLeague": {}}
    app.state.count_lock = threading.Lock()

    @app.exception_handler(ApiProblem)
    async def handle_problem(_: Request, exc: ApiProblem) -> JSONResponse:
        return problem_response(exc)

    @app.middleware("http")
    async def headers_and_host(request: Request, call_next):
        if not prepare_http_scope(request.scope, settings.public_url):
            return problem_response(ApiProblem(403, "malformed_request", "This host is not allowed to access the TEST ONLY server."))
        response = await call_next(request)
        response.headers["X-JBSL-Mock-Server"] = "true"
        response.headers["Cache-Control"] = "no-store"
        response.headers.setdefault("X-Request-ID", str(uuid4()))
        return response

    @app.get("/leaderboard/api/{league_text}")
    async def leaderboard(league_text: str):
        if not LEAGUE_PATH.fullmatch(league_text):
            raise ApiProblem(400, "malformed_request", "leagueId must be a positive decimal integer.")
        league_id = int(league_text)
        with app.state.count_lock:
            app.state.counts["leaderboard"] += 1
            by_league = app.state.counts["byLeague"]
            by_league[str(league_id)] = by_league.get(str(league_id), 0) + 1
        if control is not None:
            return await control.leaderboard(league_id)
        fixture = fixtures.get(league_id)
        if settings.proxy_fault_profile == "upstream_unavailable":
            raise ApiProblem(503, "upstream_unavailable", "Configured TEST ONLY upstream failure.")
        if settings.proxy_fault_profile == "upstream_invalid":
            return Response(content=b"{invalid", media_type="application/json", status_code=200)
        if settings.offline_upstream_dir is not None:
            path = settings.offline_upstream_dir / f"leaderboard_{league_id}.json"
            if not path.is_file():
                raise ApiProblem(404, "league_not_found", "The upstream league does not exist.")
            try:
                upstream_content = path.read_bytes()
                upstream = json.loads(upstream_content)
            except (OSError, ValueError, UnicodeError) as exc:
                raise ApiProblem(502, "upstream_invalid", "The saved upstream response is invalid.") from exc
        else:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.get(f"https://jbsl-web.herokuapp.com/leaderboard/api/{league_id}", headers={"Accept": "application/json"})
            except httpx.HTTPError as exc:
                raise ApiProblem(503, "upstream_unavailable", "The upstream leaderboard is unavailable.") from exc
            if response.status_code == 404:
                raise ApiProblem(404, "league_not_found", "The upstream league does not exist.")
            if response.status_code != 200:
                raise ApiProblem(503 if response.status_code >= 500 else 502, "upstream_unavailable" if response.status_code >= 500 else "upstream_invalid", "The upstream leaderboard failed.")
            try:
                upstream_content = response.content
                upstream = response.json()
            except ValueError as exc:
                raise ApiProblem(502, "upstream_invalid", "The upstream leaderboard returned invalid JSON.") from exc
        if fixture is None:
            return Response(content=upstream_content, media_type="application/json")
        return await app.state.scoresaber.fill(merge_leaderboard(upstream, fixture, league_id))

    @app.get("/__mock__/state")
    async def state():
        with app.state.count_lock:
            counts = json.loads(json.dumps(app.state.counts))
        return {"schemaVersion": 1, "testOnly": True, "requestCounts": counts,
                "faultProfile": control.snapshot()["behavior"]["proxy_fault"] if control else settings.proxy_fault_profile}

    @app.get("/healthz")
    async def health():
        return {"ok": True, "testOnly": True, "role": "proxy"}

    from .documentation import install_docs
    install_docs(app, "proxy")
    if control is not None:
        from .traffic import DebugTraffic
        app.add_middleware(DebugTraffic, control=control, role="proxy")

    LOG.warning("TEST ONLY / 本番利用禁止: JBSL-WEB proxy initialized")
    return app

from __future__ import annotations

from dataclasses import dataclass

import httpx

from .contracts import validate_projection
from .errors import ApiProblem


@dataclass(frozen=True)
class Identity:
    sid: str
    display_name: str
    provider: str


def bounded_response(client, method, url, *, limit=2 * 1024 * 1024, **kwargs):
    """Bound even chunked provider/upstream responses; never follow a credential redirect."""
    with client.stream(method, url, **kwargs) as response:
        data = bytearray()
        for chunk in response.iter_bytes():
            data.extend(chunk)
            if len(data) > limit:
                raise ValueError("response exceeds limit")
        return response.status_code, bytes(data)


class LeaderboardClient:
    def __init__(self, config, transport=None):
        self.config, self.transport = config, transport

    def get(self, league_id):
        from .contracts import strict_json

        headers = {"Accept": "application/json"}
        if self.config.jbsl_web_token:
            headers["Authorization"] = "Bearer " + self.config.jbsl_web_token
        try:
            with httpx.Client(
                timeout=httpx.Timeout(8, connect=3), follow_redirects=False, trust_env=False, transport=self.transport
            ) as client:
                status, body = bounded_response(
                    client,
                    "GET",
                    self.config.jbsl_web_url.rstrip("/") + f"/leaderboard/api/{league_id}",
                    headers=headers,
                )
            if status == 404:
                raise ApiProblem(404, "league_not_found", "League does not exist.")
            if status >= 500 or status == 429:
                raise ApiProblem(503, "upstream_unavailable", "JBSL-WEB is temporarily unavailable.")
            if status != 200:
                raise ValueError("unexpected HTTP status")
            projection = validate_projection(strict_json(body))
            if projection["league_id"] != league_id:
                raise ValueError("league ID mismatch")
            return projection
        except httpx.HTTPError:
            raise ApiProblem(503, "upstream_unavailable", "JBSL-WEB is temporarily unavailable.") from None
        except (ValueError, TypeError, RecursionError):
            raise ApiProblem(502, "upstream_invalid", "JBSL-WEB returned an invalid leaderboard.") from None


class TicketVerifier:
    def __init__(self, config, transport=None):
        self.config, self.transport = config, transport

    def verify(self, ticket, provider):
        from .contracts import strict_json

        if provider not in ("steamTicket", "oculusTicket"):
            raise ApiProblem(400, "malformed_request", "Unknown authentication provider.")
        if not isinstance(ticket, str) or not 1 <= len(ticket) <= 8192:
            raise ApiProblem(401, "invalid_ticket", "Ticket is invalid.")
        if provider == "steamTicket" and not self.config.steam_api_key:
            raise ApiProblem(503, "auth_provider_unavailable", "Steam authentication is not configured.")
        if provider == "oculusTicket" and not self.config.oculus_enabled:
            raise ApiProblem(503, "auth_provider_unavailable", "Oculus authentication is disabled.")
        try:
            with httpx.Client(
                timeout=httpx.Timeout(8, connect=3), follow_redirects=False, trust_env=False, transport=self.transport
            ) as client:
                if provider == "steamTicket":
                    status, body = bounded_response(
                        client,
                        "GET",
                        "https://api.steampowered.com/ISteamUserAuth/AuthenticateUserTicket/v1/",
                        limit=65536,
                        params={"appid": "620980", "key": self.config.steam_api_key, "ticket": ticket},
                    )
                else:
                    status, body = bounded_response(
                        client,
                        "GET",
                        "https://graph.oculus.com/me",
                        limit=65536,
                        params={"fields": "id,alias"},
                        headers={"Authorization": "Bearer " + ticket},
                    )
            if status in (400, 401, 403):
                raise ApiProblem(401, "invalid_ticket", "The provider rejected the ticket.")
            if status != 200:
                raise ValueError("provider status")
            data = strict_json(body)
            if not isinstance(data, dict):
                raise ValueError("provider schema")
            if provider == "steamTicket":
                envelope = data.get("response")
                params = envelope.get("params") if isinstance(envelope, dict) else None
                if not isinstance(params, dict) or params.get("result") != "OK":
                    raise ApiProblem(401, "invalid_ticket", "The provider rejected the ticket.")
                sid, name = params.get("steamid"), params.get("steamid")
            else:
                sid, name = data.get("id"), data.get("alias")
            if not isinstance(sid, str) or not sid.isascii() or not sid.isdecimal() or len(sid) > 32:
                raise ValueError("provider identity")
            return Identity(sid, name[:200] if isinstance(name, str) and name else sid, provider)
        except (httpx.HTTPError, ValueError, TypeError, RecursionError):
            raise ApiProblem(503, "auth_provider_unavailable", "The authentication provider is unavailable.") from None

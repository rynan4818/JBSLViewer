from __future__ import annotations

from typing import Any

import httpx

from ..config import Settings
from ..errors import ApiProblem
from .stub import VerifiedIdentity


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        value = response.json()
    except ValueError as exc:
        raise ApiProblem(503, "auth_provider_unavailable", "The authentication provider returned invalid data.") from exc
    if not isinstance(value, dict):
        raise ApiProblem(503, "auth_provider_unavailable", "The authentication provider returned invalid data.")
    return value


def _request(client: httpx.Client, url: str, *, params: dict[str, str] | None = None, headers: dict[str, str] | None = None) -> httpx.Response:
    try:
        return client.get(url, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise ApiProblem(503, "auth_provider_unavailable", "The authentication provider is unavailable.") from exc


def verify(ticket: str, provider: str, settings: Settings, *, transport: httpx.BaseTransport | None = None) -> VerifiedIdentity:
    if provider not in {"steamTicket", "oculusTicket"}:
        raise ApiProblem(400, "malformed_request", "provider must be steamTicket or oculusTicket.")
    if not ticket:
        raise ApiProblem(401, "invalid_ticket", "The authentication ticket was rejected.")
    with httpx.Client(timeout=10.0, transport=transport) as client:
        if provider == "steamTicket":
            if not settings.steam_api_key or not settings.steam_api_url:
                raise ApiProblem(503, "auth_provider_unavailable", "Steam real-provider-test is not configured.")
            response = _request(client, settings.steam_api_url.rstrip("/") + "/ISteamUserAuth/AuthenticateUserTicket/v1", params={"appid": "620980", "key": settings.steam_api_key, "ticket": ticket})
            if response.status_code in {400, 401, 403}:
                raise ApiProblem(401, "invalid_ticket", "The Steam ticket was rejected.")
            if response.status_code >= 500:
                raise ApiProblem(503, "auth_provider_unavailable", "The Steam authentication provider is unavailable.")
            if response.status_code != 200:
                raise ApiProblem(401, "invalid_ticket", "The Steam ticket was rejected.")
            data = _json_object(response)
            params = data.get("response", {}).get("params") if isinstance(data.get("response"), dict) else None
            sid = params.get("steamid") if isinstance(params, dict) else None
            if not isinstance(params, dict) or params.get("result") != "OK" or not isinstance(sid, str) or not sid:
                raise ApiProblem(401, "invalid_ticket", "The Steam ticket was rejected.")
            return VerifiedIdentity(sid=sid, display_name=sid, provider=provider)
        if not settings.oculus_api_url:
            raise ApiProblem(503, "auth_provider_unavailable", "Oculus real-provider-test is not configured.")
        response = _request(client, settings.oculus_api_url, params={"fields": "id,name"}, headers={"Authorization": f"Bearer {ticket}"})
        if response.status_code in {400, 401, 403}:
            raise ApiProblem(401, "invalid_ticket", "The Oculus ticket was rejected.")
        if response.status_code >= 500:
            raise ApiProblem(503, "auth_provider_unavailable", "The Oculus authentication provider is unavailable.")
        if response.status_code != 200:
            raise ApiProblem(401, "invalid_ticket", "The Oculus ticket was rejected.")
        data = _json_object(response)
        sid = data.get("id")
        if not isinstance(sid, str) or not sid:
            raise ApiProblem(401, "invalid_ticket", "The Oculus ticket was rejected.")
        display_name = data.get("name") if isinstance(data.get("name"), str) else sid
        return VerifiedIdentity(sid=sid, display_name=display_name, provider=provider)

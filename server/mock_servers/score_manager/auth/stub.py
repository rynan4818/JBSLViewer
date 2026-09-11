from __future__ import annotations

from dataclasses import dataclass

from ..errors import ApiProblem


@dataclass(frozen=True, slots=True)
class VerifiedIdentity:
    sid: str
    display_name: str
    provider: str


def verify(ticket: str, provider: str, sid: str, display_name: str) -> VerifiedIdentity:
    if provider not in {"steamTicket", "oculusTicket"}:
        raise ApiProblem(400, "malformed_request", "provider must be steamTicket or oculusTicket.")
    if not ticket or ticket == "invalid":
        raise ApiProblem(401, "invalid_ticket", "The authentication ticket was rejected.")
    return VerifiedIdentity(sid=sid, display_name=display_name, provider=provider)


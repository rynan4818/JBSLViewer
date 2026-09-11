from __future__ import annotations

from uuid import uuid4

from fastapi.responses import JSONResponse


RETRYABLE = {
    "auth_provider_unavailable",
    "upstream_unavailable",
    "upstream_invalid",
    "rate_limited",
    "internal_error",
}


class ApiProblem(Exception):
    def __init__(self, status: int, code: str, message: str, *, details: dict | None = None, retryable: bool | None = None):
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}
        self.retryable = code in RETRYABLE if retryable is None else retryable
        super().__init__(message)


def problem_response(problem: ApiProblem, request_id: str | None = None) -> JSONResponse:
    request_id = request_id or str(uuid4())
    body = {
        "error": {
            "code": problem.code,
            "message": problem.message,
            "retryable": problem.retryable,
            "requestId": request_id,
            "details": problem.details,
        }
    }
    headers = {
        "Cache-Control": "no-store",
        "X-Request-ID": request_id,
        "X-JBSL-Mock-Server": "true",
    }
    if problem.status == 429:
        headers["Retry-After"] = "60"
    return JSONResponse(body, status_code=problem.status, headers=headers)


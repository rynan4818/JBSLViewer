from uuid import uuid4

from fastapi.responses import JSONResponse


class ApiProblem(Exception):
    def __init__(self, status, code, message, *, retryable=None, details=None):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.retryable = status in (429, 502, 503, 500) if retryable is None else retryable
        self.details = details or {}


def problem_response(problem, request_id=None):
    request_id = request_id or str(uuid4())
    headers = {"Cache-Control": "no-store", "X-Request-ID": request_id}
    if problem.status in (429, 503):
        headers["Retry-After"] = "5" if problem.status == 503 else "60"
    return JSONResponse(
        {
            "error": {
                "code": problem.code,
                "message": problem.message,
                "retryable": problem.retryable,
                "requestId": request_id,
                "details": problem.details,
            }
        },
        status_code=problem.status,
        headers=headers,
    )

"""Offline Swagger UI for the actual relay and Viewer HTTP endpoints."""
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import ROOT


def obj(properties, required=None):
    return {"type": "object", "properties": properties, "required": list(properties) if required is None else required}


def nullable(value):
    return {"anyOf": [value, {"type": "null"}]}


def schemas():
    text = {"type": "string"}
    number = {"type": "number"}
    boolean = {"type": "boolean"}
    integer = {"type": "integer", "minimum": 0}
    date = {"type": "string", "format": "date-time"}
    uuid = {"type": "string", "format": "uuid"}
    array = lambda item: {"type": "array", "items": item}
    ref = lambda name: {"$ref": "#/components/schemas/" + name}
    version = {"type": "integer", "const": 1}
    map_key = obj({"hash": {"type": "string", "pattern": "^[0-9A-Fa-f]{40}$"}, "characteristic": text,
                   "difficulty": {"type": "string", "enum": ["Easy", "Normal", "Hard", "Expert", "ExpertPlus"]}})
    map_key["example"] = {"hash": "0123456789ABCDEF0123456789ABCDEF01234567", "characteristic": "Standard", "difficulty": "ExpertPlus"}
    map_status = obj({**map_key["properties"], "title": nullable(text), "attemptLimit": nullable({"type": "integer", "minimum": 1, "maximum": 100}),
                      "attemptScope": {"type": "string", "const": "per_player_per_map"}})
    timing = obj({**{k: nullable(date) for k in ("confirmedAtClient", "reserveResponseReceivedAtClient", "startedAtClient", "endedAtClient", "resultFinalizedAtClient")},
                  **{k: nullable(number) for k in ("localSongDurationSeconds", "songSpeedMultiplier", "totalPauseSeconds")}})
    metadata = obj({"schemaVersion": version, "clientResultId": uuid, "challengeId": uuid, "map": ref("MapKey"),
                    "endState": {"type": "string", "enum": ["cleared", "failed", "incomplete", "unknown"]},
                    "endAction": {"type": "string", "enum": ["none", "quit", "restart", "unknown"]},
                    "endType": {"type": "string", "enum": ["clear", "fail", "quit", "restart", "unknown", "preflight_rejected"]},
                    **{k: nullable(integer) for k in ("multipliedScore", "modifiedScore", "maxPossibleModifiedScore", "missedCount", "badCutsCount", "goodCutsCount", "maxCombo")},
                    "endSongTime": nullable(number), "fullCombo": nullable(boolean), "energy": nullable(number), "modifiers": nullable(array(text)),
                    "submissionEligibility": obj({"allowedAtStart": boolean, "remainedAllowed": boolean, "blockers": array(text)}),
                    "scoreValidity": obj({"validForRanking": boolean, "invalidReason": nullable(text), "restartDetected": boolean, "playInstanceCount": integer}),
                    "timing": timing, "clientVersion": {"type": "string", "minLength": 1}, "gameVersion": {"type": "string", "minLength": 1}})
    metadata["properties"]["diagnostics"] = nullable(obj({"failureCode": nullable(text), "actualMap": nullable(ref("MapKey")), "replayGenerationFailed": nullable(boolean)}, []))
    return {
        "MapKey": map_key,
        "Error": obj({"error": obj({"code": text, "message": text, "retryable": boolean, "requestId": uuid, "details": {"type": "object"}}, ["code", "message", "retryable", "requestId"])}),
        "Leaderboard": obj({"league_id": {"type": "integer", "minimum": 1}, "league_title": text, "isLive": boolean, "isOpen": boolean, "end": date,
                            "participants": array(obj({"sid": text})),
                            "qualifier": obj({"enabled": boolean, "submission_method": {"type": "string", "enum": ["external_leaderboard", "jbsl_qualifier_v1"]},
                                              "revision": text, "starts_at": nullable(date), "ends_at": nullable(date)}),
                            "total_rank": array({"type": "object"}),
                            "maps": array(obj({**map_key["properties"], "title": text, "lid": text, "bsr": text,
                                               "song_duration_seconds": nullable({"type": "number", "exclusiveMinimum": 0}),
                                               "qualifier_attempt_limit": nullable({"type": "integer", "minimum": 1, "maximum": 100}), "scores": array({"type": "object"})}))}),
        "Session": obj({"schemaVersion": version, "authenticated": boolean, "user": obj({"sid": text, "displayName": text}), "expiresAt": date}),
        "Status": obj({"schemaVersion": version, "serverTime": date, "eligible": boolean, "reasonCode": text,
                       "league": nullable(obj({"id": {"type": "integer", "minimum": 1}, "name": text, "submissionMethod": text, "revision": text})),
                       "map": nullable(map_status), "isParticipant": nullable(boolean), "remainingAttempts": nullable(integer),
                       "cache": obj({"fetchedAt": nullable(date), "stale": boolean})}),
        "ReserveRequest": obj({"schemaVersion": version, "leagueId": {"type": "integer", "minimum": 1, "default": 3023}, "map": ref("MapKey"),
                               "clientVersion": {"type": "string", "minLength": 1, "default": "JBSLViewer/debug"},
                               "gameVersion": {"type": "string", "minLength": 1, "default": "1.29.1"}}),
        "Reserve": obj({"schemaVersion": version, "challengeId": uuid, "status": text,
                        "map": ref("MapKey"), "attemptNumber": integer, "attemptLimit": integer, "remainingAttempts": integer, "reservedAt": date, "resultAcceptUntil": date}),
        "StartedRequest": obj({"schemaVersion": version, "actualMap": ref("MapKey"), "gameMode": {"type": "string", "const": "Solo"},
                               "practice": {"type": "boolean", "const": False}, "submissionAllowed": {"type": "boolean", "const": True}, "startedAtClient": date}),
        "Started": obj({"schemaVersion": version, "challengeId": uuid, "status": text, "startedAt": date}),
        "ResultMetadata": metadata,
        "Result": obj({"schemaVersion": version, "challengeId": uuid, "submissionId": uuid, "status": text, "validForRanking": boolean,
                       "invalidReason": nullable(text), "replaySha256": nullable(text), "remainingAttempts": integer, "receivedAt": date}),
    }


def enrich(document, role):
    document["components"] = {"schemas": schemas(), "securitySchemes": {"ViewerSession": {"type": "apiKey", "in": "cookie", "name": "jbslq_session"}}}
    document["info"]["description"] = "ローカルデバッグ専用。Try it out はこのポートの実 API に送信します。設定した障害・遅延も適用されます。"
    document["servers"] = [{"url": "/", "description": "この Swagger UI と同じローカルサーバ"}]

    def response(name):
        return {"description": "正常応答", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/" + name}}}}

    def param(name, schema, location="query"):
        return {"name": name, "in": location, "required": True, "schema": schema}

    def body(name, media="application/json"):
        return {"required": True, "content": {media: {"schema": {"$ref": "#/components/schemas/" + name}}}}

    error_responses = {str(code): {"description": label, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
                       for code, label in ((400, "要求不正"), (401, "再認証が必要"), (403, "対象外"), (404, "不存在"),
                                           (409, "設定不足・競合・受付期限超過"), (422, "値不正"), (429, "制限・Retry-After"), (502, "上流不正"), (503, "一時障害"))}
    if role == "proxy":
        op = document["paths"]["/leaderboard/api/{league_text}"]["get"]
        op.update(summary="Qualifier 設定を反映したリーグ情報", tags=["JBSL-WEB 中継"],
                  parameters=[param("league_text", {"type": "string", "pattern": "^[1-9][0-9]*$", "default": "3023"}, "path")],
                  responses={"200": response("Leaderboard"), **error_responses})
        return document
    prefix = "/api/v1"
    session = document["paths"][prefix + "/auth/session"]
    session["post"].update(summary="テスト SID のセッションを作成", tags=["Viewer 認証"], responses={"200": response("Session"), **error_responses},
                           requestBody={"required": True, "content": {"application/x-www-form-urlencoded": {"schema": obj({
                               "ticket": {"type": "string", "default": "local-debug-ticket"},
                               "provider": {"type": "string", "enum": ["steamTicket", "oculusTicket"], "default": "steamTicket"},
                               "returnUrl": {"type": "string", "default": "/"}})}}})
    document["paths"][prefix + "/auth/me"]["get"].update(summary="認証済み SID を確認", tags=["Viewer 認証"], responses={"200": response("Session"), **error_responses})
    session["delete"].update(summary="セッションを失効", tags=["Viewer 認証"], responses={"204": {"description": "失効済み"}, **error_responses})
    status = document["paths"][prefix + "/qualifiers/status"]["get"]
    status.update(summary="参加資格・残回数を取得", tags=["Challenge"], responses={"200": response("Status"), **error_responses},
                  parameters=[param("leagueId", {"type": "integer", "minimum": 1, "default": 3023}),
                              *[param(k, {"type": "string", "default": v}) for k, v in schemas()["MapKey"]["example"].items()]])
    reserve = document["paths"][prefix + "/qualifiers/challenges"]["post"]
    reserve.update(summary="最新情報を確認して予約・1回消費", tags=["Challenge"], requestBody=body("ReserveRequest"),
                   parameters=[param("Idempotency-Key", {"type": "string", "format": "uuid"}, "header")],
                   responses={"201": response("Reserve"), "200": response("Reserve"), **error_responses})
    start = document["paths"][prefix + "/qualifiers/challenges/{challenge_id}/started"]["post"]
    start.update(summary="ゲーム開始を通知", tags=["Challenge"], requestBody=body("StartedRequest"), responses={"200": response("Started"), **error_responses})
    result = document["paths"][prefix + "/qualifiers/challenges/{challenge_id}/result"]["put"]
    result.update(summary="結果と任意の BSOR gzip を提出", tags=["Challenge"],
                  description="metadata は ResultMetadata の JSON 文字列。ランキング採用候補 clear/fail には replay が必須です。",
                  parameters=[param("challenge_id", {"type": "string", "format": "uuid"}, "path"), param("Idempotency-Key", {"type": "string", "format": "uuid"}, "header")],
                  requestBody={"required": True, "content": {"multipart/form-data": {"schema": obj({"metadata": {"type": "string", "description": "ResultMetadata JSON"},
                                                                                                           "replay": {"type": "string", "format": "binary"}}, ["metadata"])}}},
                  responses={"201": response("Result"), "200": response("Result"), **error_responses})
    for path, methods in document["paths"].items():
        if path.startswith(prefix):
            for method, operation in methods.items():
                if not (path.endswith("/auth/session") and method == "post"):
                    operation["security"] = [{"ViewerSession": []}]
    return document


def install_docs(app: FastAPI, role):
    app.mount("/docs-assets", StaticFiles(directory=ROOT / "static"), name="docs-assets")

    @app.get("/docs", include_in_schema=False)
    async def docs():
        return FileResponse(ROOT / "static/swagger.html")

    original = app.openapi

    def openapi():
        if app.openapi_schema is None:
            app.openapi_schema = enrich(original(), role)
        return app.openapi_schema
    app.openapi = openapi

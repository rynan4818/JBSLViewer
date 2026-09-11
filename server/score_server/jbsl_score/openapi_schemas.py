"""Documentation schemas for the strict, manually validated wire protocol.

These schemas describe requests; they never replace the runtime validators.
"""

from dataclasses import asdict

from .config import Policy, REFUND_CONDITIONS


def ref(name):
    return {"$ref": "#/components/schemas/" + name}


def obj(properties, *, required=None, closed=False, **kwargs):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else required,
        "additionalProperties": not closed,
        **kwargs,
    }


def string(description="", **kwargs):
    return {"type": "string", "description": description, **kwargs}


def integer(description="", minimum=0, **kwargs):
    return {"type": "integer", "minimum": minimum, "description": description, **kwargs}


def boolean(description="", **kwargs):
    return {"type": "boolean", "description": description, **kwargs}


def nullable(schema):
    return {"anyOf": [schema, {"type": "null"}]}


def array(schema, **kwargs):
    return {"type": "array", "items": schema, **kwargs}


UUID = string("UUID。再送時は同じ値を使用します。", format="uuid")
DATE = string("タイムゾーンを含む日時。応答はUTCのISO 8601形式。", format="date-time")
VERSION = integer("現行のスキーマバージョン。", minimum=1, const=1)
SID = string("Steam / OculusのプレイヤーID。数値化せず文字列として扱います。", minLength=1, maxLength=128)
LEAGUE = integer("JBSL-WEBのLeague ID。", minimum=1, maximum=2147483647)
SCORE = nullable(integer("未取得時はnull。", maximum=2147483647))
SHA = nullable(string("未圧縮BSORのSHA-256。Replayがない場合はnull。", pattern="^[0-9a-f]{64}$"))
END_TYPE = string(enum=["clear", "fail", "quit", "restart", "unknown", "preflight_rejected"])
REASON = nullable(
    string(enum=["quit", "restarted", "unknown", "preflight_rejected", "submission_disabled", "replay_unavailable"])
)
STATUS = string(enum=["reserved", "started", "submitted", "abandoned"])
MAP_EXAMPLE = {
    "hash": "0123456789ABCDEF0123456789ABCDEF01234567",
    "characteristic": "Standard",
    "difficulty": "ExpertPlus",
}

# Keep bounds consistent with Policy.parse; the contract test verifies both edges.
POLICY_FIELDS = {
    "result_grace_seconds": (0, 604800, "終了後の提出猶予（秒）。受付期限=実効終了日時+猶予。予約時に固定。"),
    "challenge_timeout_seconds": (0, 604800, "予約からの運用タイムアウト（秒）。0は無効。予約時に固定。"),
    "max_active_per_user": (0, 100, "ユーザー全体の未提出Challenge上限。0は無制限。"),
    "cache_fresh_seconds": (0, 60, "statusで再利用する上流キャッシュの秒数。新規予約は常に再取得。"),
    "cache_stale_seconds": (0, 300, "上流到達不能時の参考表示期限（取得からの秒数）。通常キャッシュ以上。"),
    "session_seconds": (300, 86400, "新しく発行するViewerセッションの有効秒数。"),
    "max_sessions_per_user": (1, 20, "再認証時に保持するViewerセッション数。古いものから失効。"),
    "auth_per_minute": (1, 600, "IPごとの認証要求上限 / 分。"),
    "status_per_minute": (1, 600, "ユーザーごとのstatus、meそれぞれの要求上限 / 分。"),
    "reserve_per_minute": (1, 600, "ユーザーごとの予約要求上限 / 分。再送も含む。"),
    "result_per_minute": (1, 600, "ユーザーごとの結果提出、開始通知それぞれの要求上限 / 分。"),
    "min_free_disk_mb": (64, 1048576, "予約・新規結果保存に必要な空き容量（MB）。"),
    "backup_interval_hours": (0, 168, "自動バックアップの間隔（時間）。0は自動作成を停止。"),
    "backup_keep_count": (1, 100, "検証済みバックアップの保持数。新規作成後に古い世代を削除。"),
}


def schemas():
    result = {}
    result["MapKey"] = obj(
        {
            "hash": string("40桁の譜面hash。前後空白を除去し大文字に正規化。", pattern="^[0-9A-Fa-f]{40}$"),
            "characteristic": string(
                "譜面特性。hash・difficultyと合わせて同一譜面を判定。",
                minLength=1,
                maxLength=100,
                examples=["Standard"],
            ),
            "difficulty": string(
                "Expert+ / Expert PlusはExpertPlusに正規化。",
                enum=["Easy", "Normal", "Hard", "Expert", "ExpertPlus", "Expert+", "Expert Plus"],
            ),
        },
        closed=True,
        examples=[MAP_EXAMPLE],
    )
    result["Error"] = obj(
        {
            "error": obj(
                {
                    "code": string("機械判定用のエラーコード。", examples=["result_acceptance_expired"]),
                    "message": string("説明文。"),
                    "retryable": boolean("同一payload・キーでの再試行が可能か。"),
                    "requestId": UUID,
                    "details": obj({}, required=[]),
                }
            )
        }
    )
    result["PlayerSession"] = obj(
        {
            "schemaVersion": VERSION,
            "authenticated": boolean(const=True),
            "user": obj({"sid": SID, "displayName": string()}),
            "expiresAt": DATE,
        }
    )
    result["AuthForm"] = obj(
        {
            "ticket": string(
                "Steamのticket、またはOculusアクセストークン。秘密情報。", minLength=1, maxLength=8192, writeOnly=True
            ),
            "provider": string(enum=["steamTicket", "oculusTicket"]),
            "returnUrl": string("省略時は /。他の値は受け付けません。", const="/", default="/"),
        },
        required=["ticket", "provider"],
        closed=True,
    )
    result["ReserveRequest"] = obj(
        {
            "schemaVersion": VERSION,
            "leagueId": LEAGUE,
            "map": ref("MapKey"),
            "clientVersion": string(minLength=1, maxLength=100),
            "gameVersion": string(minLength=1, maxLength=100),
        },
        closed=True,
        examples=[
            {
                "schemaVersion": 1,
                "leagueId": 3023,
                "map": MAP_EXAMPLE,
                "clientVersion": "JBSLViewer/1.0",
                "gameVersion": "1.29.1",
            }
        ],
    )
    result["Reservation"] = obj(
        {
            "schemaVersion": VERSION,
            "challengeId": UUID,
            "status": string(const="reserved"),
            "attemptNumber": integer("返却後も再利用しない通し番号。", minimum=1),
            "attemptLimit": integer(minimum=1),
            "remainingAttempts": integer(),
            "reservedAt": DATE,
            "resultAcceptUntil": DATE,
            "map": ref("MapKey"),
        }
    )
    result["StartedRequest"] = obj(
        {
            "schemaVersion": VERSION,
            "actualMap": ref("MapKey"),
            "gameMode": string(const="Solo"),
            "practice": boolean(const=False),
            "submissionAllowed": boolean(const=True),
            "startedAtClient": DATE,
        },
        closed=True,
    )
    result["Started"] = obj(
        {"schemaVersion": VERSION, "challengeId": UUID, "status": string(const="started"), "startedAt": DATE}
    )
    result["QualifierStatus"] = obj(
        {
            "schemaVersion": VERSION,
            "serverTime": DATE,
            "eligible": boolean("参加資格。残回数0でもtrueになり得るためreasonCodeも確認。"),
            "reasonCode": string(
                enum=[
                    "eligible",
                    "league_not_found",
                    "qualifier_disabled",
                    "wrong_submission_method",
                    "league_not_open",
                    "outside_qualifier_window",
                    "map_not_found",
                    "not_participant",
                    "attempts_exhausted",
                    "upstream_unavailable",
                ]
            ),
            "league": nullable(
                obj({"id": LEAGUE, "name": string(), "submissionMethod": string(), "revision": string()})
            ),
            "map": nullable(
                obj(
                    {
                        **result["MapKey"]["properties"],
                        "title": nullable(string()),
                        "attemptLimit": nullable(integer(minimum=1)),
                        "attemptScope": string(const="per_player_per_map"),
                    }
                )
            ),
            "isParticipant": nullable(boolean()),
            "remainingAttempts": nullable(integer()),
            "cache": obj({"fetchedAt": DATE, "stale": boolean("trueの場合は参考表示であり予約許可ではない。")}),
        }
    )
    result["ResultMetadata"] = obj(
        {
            "schemaVersion": VERSION,
            "clientResultId": UUID,
            "challengeId": UUID,
            "map": ref("MapKey"),
            "endState": string(enum=["cleared", "failed", "incomplete", "unknown"]),
            "endAction": string(enum=["none", "quit", "restart", "unknown"]),
            "endType": END_TYPE,
            "endSongTime": nullable({"type": "number", "minimum": 0}),
            **{
                key: SCORE
                for key in (
                    "multipliedScore",
                    "modifiedScore",
                    "maxPossibleModifiedScore",
                    "missedCount",
                    "badCutsCount",
                    "goodCutsCount",
                    "maxCombo",
                )
            },
            "fullCombo": nullable(boolean()),
            "energy": nullable({"type": "number"}),
            "modifiers": nullable(array(string())),
            "submissionEligibility": obj(
                {"allowedAtStart": boolean(), "remainedAllowed": boolean(), "blockers": array(string())}, closed=True
            ),
            "scoreValidity": obj(
                {
                    "validForRanking": boolean(),
                    "invalidReason": REASON,
                    "restartDetected": boolean(),
                    "playInstanceCount": integer(maximum=1),
                },
                closed=True,
            ),
            "timing": obj(
                {
                    **{
                        key: nullable(DATE)
                        for key in (
                            "confirmedAtClient",
                            "reserveResponseReceivedAtClient",
                            "startedAtClient",
                            "endedAtClient",
                            "resultFinalizedAtClient",
                        )
                    },
                    "localSongDurationSeconds": nullable({"type": "number", "exclusiveMinimum": 0}),
                    "songSpeedMultiplier": nullable({"type": "number", "exclusiveMinimum": 0}),
                    "totalPauseSeconds": nullable({"type": "number", "minimum": 0}),
                },
                closed=True,
            ),
            "clientVersion": string(minLength=1),
            "gameVersion": string(minLength=1),
            "diagnostics": nullable(
                obj(
                    {
                        "failureCode": nullable(string()),
                        "actualMap": nullable(ref("MapKey")),
                        "replayGenerationFailed": nullable(boolean()),
                    },
                    required=[],
                    closed=True,
                )
            ),
        },
        closed=True,
        description="metadataパートのUTF-8 JSON。diagnostics以外はnullでもキー必須。終了理由の組合せは図付き解説の回数返却を参照。ランキング候補は3つのスコア値とReplayが必要。BSOR scoreはmultipliedScoreと一致、modifiedScoreは最大値以下。",
    )
    result["ResultMetadata"]["required"].remove("diagnostics")
    result["ResultReceipt"] = obj(
        {
            "schemaVersion": VERSION,
            "submissionId": UUID,
            "challengeId": UUID,
            "status": string(const="submitted"),
            "validForRanking": boolean(),
            "invalidReason": REASON,
            "receivedAt": DATE,
            "replaySha256": SHA,
            "remainingAttempts": integer(),
        }
    )
    result["Submission"] = obj(
        {
            "submissionId": UUID,
            "challengeId": UUID,
            "sid": SID,
            "leagueId": LEAGUE,
            "map": ref("MapKey"),
            "endType": END_TYPE,
            **{
                key: SCORE
                for key in (
                    "modifiedScore",
                    "maxPossibleModifiedScore",
                    "multipliedScore",
                    "missedCount",
                    "badCutsCount",
                    "goodCutsCount",
                )
            },
            "accuracyPercent": nullable({"type": "number", "minimum": 0, "maximum": 100}),
            "validForRanking": boolean("元提出がランキング対象か。管理者操作では変わりません。"),
            "invalidReason": REASON,
            "canceled": boolean("管理者による取消状態。"),
            "effectiveForRanking": boolean("validForRanking && !canceled。現在の採否。"),
            "moderationVersion": integer("取消・復元の競合検出用。"),
            "moderationReason": nullable(string()),
            "receivedAt": DATE,
            "replaySha256": SHA,
            "attemptRefunded": boolean(),
            "refundReason": nullable(string(enum=sorted(REFUND_CONDITIONS | {"admin_manual"}))),
        }
    )
    result["SubmissionResponse"] = obj({"schemaVersion": VERSION, **result["Submission"]["properties"]})
    result["Changes"] = obj(
        {
            "schemaVersion": VERSION,
            "items": array(
                obj(
                    {
                        "seq": integer(minimum=1),
                        "event": string(enum=["submitted", "canceled", "restored", "attempt_refunded"]),
                        "occurredAt": DATE,
                        "submission": ref("Submission"),
                    }
                )
            ),
            "nextCursor": integer("正常に取り込んだページの後で保存するcursor。空ページでも進むことがあります。"),
            "hasMore": boolean(),
            "highWatermark": integer("この読取り時点で存在した最大seq。"),
        }
    )
    result["Leaderboard"] = obj(
        {
            "schemaVersion": VERSION,
            "leagueId": LEAGUE,
            "items": array(
                obj(
                    {
                        **result["Submission"]["properties"],
                        "rank": integer("譜面内の順位。同点は1,1,3方式。", minimum=1),
                    }
                )
            ),
        }
    )
    result["AdminRankings"] = obj(
        {
            "leagues": array(obj({"leagueId": LEAGUE, "title": string()})),
            "leagueId": nullable(LEAGUE),
            "maps": array(obj({
                **result["MapKey"]["properties"],
                "title": string(),
                "attemptLimit": nullable(integer("最後に検証した上流の回数上限。不明ならnull。", minimum=1, maximum=100)),
                "songDurationSeconds": nullable({"type": "number", "exclusiveMinimum": 0, "description": "曲時間（秒）。不明ならnull。"}),
            })),
            "items": array(obj({
                **result["Submission"]["properties"],
                "rank": integer("譜面内の順位。同点は1,1,3方式。", minimum=1),
                "displayName": string(),
                "remainingAttempts": nullable(integer("現在の未返却使用回数を上限から引いた残回数。上限が不明ならnull。")),
            })),
        }
    )
    ranking = result["AdminRankings"]["properties"]
    result["PublicRankings"] = obj(
        {
            "leagues": array(obj({"leagueId": LEAGUE, "title": string()}, closed=True)),
            "leagueId": nullable(LEAGUE),
            "maps": array(obj({
                field: ranking["maps"]["items"]["properties"][field]
                for field in ("hash", "characteristic", "difficulty", "title", "attemptLimit", "songDurationSeconds")
            }, closed=True)),
            "items": array(obj({
                **{
                    field: ranking["items"]["items"]["properties"][field]
                    for field in (
                        "rank", "sid", "displayName", "map", "modifiedScore", "accuracyPercent",
                        "remainingAttempts", "receivedAt", "endType",
                    )
                },
                "replay": obj({
                    "downloadUrl": nullable(string("公開Replayのgzipダウンロード相対URL。Replayなしはnull。", format="uri-reference")),
                    "beatleaderUrl": nullable(string("BeatLeaderの再生URL。Replayなし・HTTPS未設定はnull。", format="uri")),
                    "arcviewerUrl": nullable(string("ArcViewerの再生URL。Replayなし・HTTPS未設定はnull。", format="uri")),
                }, closed=True),
            }, closed=True)),
        },
        closed=True,
    )
    result["Attempts"] = obj(
        {
            "items": array(
                obj(
                    {
                        "leagueId": LEAGUE,
                        "map": ref("MapKey"),
                        "usedAttempts": integer("未返却の使用回数。"),
                        "totalChallenges": integer(),
                        "refundedAttempts": integer(),
                        "attemptLimit": nullable(integer(minimum=1)),
                        "remainingAttempts": nullable(integer()),
                    }
                )
            ),
            "limitSource": string(const="last validated JBSL-WEB cache"),
        }
    )
    result["AttemptsResponse"] = obj({"schemaVersion": VERSION, **result["Attempts"]["properties"]})
    result["AdminSession"] = obj(
        {"username": string(), "csrfToken": string("更新要求のX-CSRF-Tokenに設定。秘密情報。"), "expiresAt": DATE}
    )
    result["AdminLogin"] = obj(
        {
            "username": string(minLength=1, maxLength=64),
            "password": string(minLength=12, maxLength=256, writeOnly=True),
        },
        closed=True,
    )
    result["ReplayViewerRequest"] = obj({"viewer": string(enum=["beatleader", "arcviewer"])}, closed=True)
    result["ReplayViewerLink"] = obj({"viewerUrl": string(format="uri"), "expiresAt": DATE})
    defaults = asdict(Policy())
    policy = {
        key: integer(description, minimum=low, maximum=high, default=defaults[key])
        for key, (low, high, description) in POLICY_FIELDS.items()
    }
    policy.update(
        {
            "reservations_enabled": boolean("新規予約の受付可否。予約済みの結果提出は停止しません。", default=True),
            "start_deadline_policy": string(
                "新規予約の締切判定。曲時間方式でduration不明の場合は予約拒否。",
                enum=["effective_end", "end_minus_duration"],
                default="effective_end",
            ),
            "refund_conditions": array(
                string(enum=sorted(REFUND_CONDITIONS)),
                uniqueItems=True,
                default=[],
                description="受理したスコア対象外結果と未着確定に対する返却条件。予約時に固定。",
            ),
        }
    )
    result["Policy"] = obj(policy, closed=True)
    result["Settings"] = obj(
        {"revision": integer("GETで取得した現在のリビジョン。古い更新は409。"), "policy": ref("Policy")}, closed=True
    )
    result["ModerationRequest"] = obj(
        {
            "action": string(enum=["cancel", "restore"]),
            "version": integer("現在のmoderationVersion。"),
            "reason": string("前後空白を除去して1～500文字。", minLength=1, maxLength=500),
        },
        closed=True,
    )
    result["SubmissionDetail"] = obj(
        {
            **result["Submission"]["properties"],
            "metadata": ref("ResultMetadata"),
            "reservationPolicy": ref("Policy"),
            "policyRevision": integer(),
            "replayViewerAvailable": boolean("外部再生用API公開URLがHTTPSならtrue。到達性の保証ではありません。"),
        }
    )
    result["ForceEndRequest"] = obj(
        {"reason": string("前後の空白を除いて1～500文字の操作理由。", minLength=1, maxLength=500, pattern=r"\S"),
         "refundAttempt": boolean("同時に1回返却する場合はtrue。", default=False)},
        closed=True,
    )
    result["RefundRequest"] = obj({"reason": result["ForceEndRequest"]["properties"]["reason"]}, closed=True)
    result["ChallengeControl"] = obj(
        {"challengeId": UUID, "status": STATUS, "abandonedReason": nullable(string()),
         "attemptRefunded": boolean(), "refundReason": nullable(string())}
    )
    result["ChallengeList"] = obj(
        {
            "items": array(
                obj(
                    {
                        "challengeId": UUID,
                        "sid": SID,
                        "leagueId": LEAGUE,
                        "map": ref("MapKey"),
                        "status": STATUS,
                        "abandonedReason": nullable(string("admin_force_endedは管理者による強制終了。")),
                        "attemptNumber": integer(minimum=1),
                        "attemptLimit": integer(minimum=1),
                        "reservedAt": DATE,
                        "startedAt": nullable(DATE),
                        "resultAcceptUntil": DATE,
                        "timeoutAt": nullable(DATE),
                        "attemptRefunded": boolean(),
                        "refundReason": nullable(string()),
                        "submissionId": nullable(UUID),
                        "endType": nullable(END_TYPE),
                        "modifiedScore": SCORE,
                        "validForRanking": boolean(),
                        "canceled": boolean(),
                    }
                )
            ),
            "nextCursor": nullable(integer()),
        }
    )
    result["UserList"] = obj(
        {
            "items": array(
                obj({"sid": SID, "displayName": string(), "challenges": integer(), "submissions": integer()})
            ),
            "nextCursor": nullable(string()),
        }
    )
    result["AuditList"] = obj(
        {
            "items": array(
                obj(
                    {
                        "id": integer(minimum=1),
                        "occurredAt": DATE,
                        "actor": string(),
                        "event": string(),
                        "challengeId": nullable(UUID),
                        "requestId": nullable(string()),
                        "elapsedMs": nullable({"type": "number", "minimum": 0,
                                               "description": "受付・操作開始からログ記録までのミリ秒。過去の未計測ログはnull。"}),
                        "details": obj({}, required=[]),
                    }
                )
            ),
            "nextCursor": nullable(integer()),
        }
    )
    result["Dashboard"] = obj(
        {
            "serverTime": DATE,
            "counts": obj(
                {
                    key: integer()
                    for key in ("reserved", "started", "submitted", "abandoned", "users", "ranked", "canceled")
                }
            ),
            "cache": array(obj({"leagueId": LEAGUE, "fetchedAt": DATE, "lastError": nullable(string())})),
            "diskFreeMb": integer(),
            "databaseMb": {"type": "number", "minimum": 0},
            "maintenance": {
                "type": "object",
                "additionalProperties": string(),
                "description": "last_backup / last_backup_file / last_backup_error等。未実行時はキーなし。",
            },
            "serviceTokens": array(obj({"name": string(), "createdAt": DATE, "revoked": boolean()})),
            "authentication": obj({"steamConfigured": boolean(), "oculusEnabled": boolean()}),
        }
    )
    result["Backup"] = obj(
        {
            "file": string(),
            "integrity": string(const="ok"),
            "replaysChecked": integer(),
            "challenges": integer(),
            "results": integer(),
        }
    )
    result["CacheRefresh"] = obj({"leagueId": LEAGUE, "revision": string(), "fetchedAt": DATE})
    result["Health"] = obj({"status": string(const="ok"), "service": string(const="jbsl-score"), "version": string()})
    result["Readiness"] = obj({"status": string(const="ok"), "database": string(const="ok")})
    return result

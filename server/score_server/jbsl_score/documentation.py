"""Public, read-only documentation on the administration listener only."""

from .replay_viewer import PUBLIC_DOWNLOAD_PATH, PUBLIC_REPLAY_PATH
from .openapi_schemas import (
    LEAGUE,
    SID,
    STATUS,
    UUID,
    integer,
    obj,
    ref,
    schemas,
    string,
)


def parameter(name, schema, description="", *, location="query", required=False):
    return {
        "name": name,
        "in": location,
        "required": required or location == "path",
        "schema": schema,
        "description": description,
    }


def build_openapi(config):
    models = schemas()
    document = {
        "openapi": "3.1.0",
        "info": {
            "title": "JBSL Score Server API",
            "version": "1.0.0",
            "description": "Viewer、jbsl-web連携、管理画面のAPI仕様です。**このSwagger UIは閲覧専用**です。"
            "各操作の接続先はServersで確認できます。Viewer・連携APIはネイティブ／サーバークライアント用で、ブラウザのOrigin付き要求を拒否します。"
            "専用の外部Replay配信APIは許可したビューアOriginで読み込めます。"
            "公開ランキングのReplayは認証不要、管理者用Replayは期限付きトークンが必要です。"
            "\n\n日時はUTC、スコア未取得値はnull、再送は同じ内容とキーを維持してください。"
            "管理用Cookie・Viewer用Cookie・連携用Bearerは相互に代用できません。"
            "\n\n[図付き運用ガイド](/admin/guide/) · [管理画面](/admin/)",
        },
        "servers": [{"url": config.api_public_url.rstrip("/"), "description": "Viewer・jbsl-web連携API"}],
        "tags": [
            {"name": "公開ランキング", "description": "ログイン不要のランキング表示と、現在採用されている提出のReplay取得・再生。"},
            {"name": "外部Replay再生", "description": "提出ごと・最長10分の閲覧用URL。管理者ログアウトでも失効します。"},
            {"name": "Viewer認証", "description": "ticket検証とHttpOnly Cookieによるセッション。"},
            {
                "name": "Challenge",
                "description": "資格確認 → 予約（1回消費）→ 開始 → 結果提出。[期限と再送の解説](/admin/guide/#deadlines)",
            },
            {
                "name": "jbsl-web連携",
                "description": "読取り専用Bearerトークン。作成: `.venv\\Scripts\\python.exe -m jbsl_score create-token jbsl-web`。[取り込み手順](/admin/guide/#integration)",
            },
            {
                "name": "管理ログイン",
                "description": "管理ポート専用。ログイン8時間、更新操作にはCookieとCSRFの両方が必要。",
            },
            {
                "name": "管理・閲覧",
                "description": "実データは管理者ログインが必要です。API仕様の閲覧だけならログイン不要。",
            },
            {
                "name": "管理・変更",
                "description": "強制終了、手動返却、設定変更、取消／復元、バックアップ。変更履歴は監査ログへ記録します。",
            },
            {
                "name": "監視",
                "description": "APIポートの稼働確認。認証不要。外部サービスの正常性を保証する検査ではありません。",
            },
        ],
        "paths": {},
        "components": {
            "schemas": models,
            "securitySchemes": {
                "ReplayViewerToken": {
                    "type": "apiKey", "in": "query", "name": "token",
                    "description": "管理者が発行した対象Replay専用トークン。Cookieや連携Bearerは代用不可。最長10分。",
                },
                "ViewerSession": {
                    "type": "apiKey",
                    "in": "cookie",
                    "name": "jbslq_session",
                    "description": "Viewer認証で発行。Path=/、HttpOnly、SameSite=Lax。HTTPSではSecure。",
                },
                "IntegrationBearer": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "CLIで発行した読取り専用サービストークン。Authorization: Bearer <token>。",
                },
                "AdminSession": {
                    "type": "apiKey",
                    "in": "cookie",
                    "name": "jbslq_admin",
                    "description": "管理ログインで発行。Path=/admin、HttpOnly、SameSite=Strict。",
                },
                "AdminCsrf": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-CSRF-Token",
                    "description": "管理ログインまたはGET /admin/api/meのcsrfToken。更新時にCookieと両方必要。",
                },
            },
        },
    }
    errors = {
        400: "要求形式・型・Host不正（malformed_request / invalid_host）。",
        401: "未認証・失効・認証失敗（authentication_required / invalid_ticket / admin_login_required / invalid_login / service_authentication_required）。",
        403: "参加資格・所有者・Origin・CSRF・HTTPS条件に不一致。",
        404: "対象League・譜面・Challenge・提出・Replayが存在しません。",
        408: "本文の読込みが制限時間を超過、または通信切断（request_timeout）。",
        409: "期限超過・残回数不足・再送内容不一致・更新競合。再読込みして状態を確認してください。",
        413: "本文・metadata・Replayの容量制限を超過。",
        422: "metadataの値や終了理由、譜面、Replayの整合性に問題があります。",
        429: "要求回数制限。Retry-After: 60。再送でも要求回数に数えます。",
        500: "内部エラー。requestIdで監査／エラーログを確認してください。",
        502: "上流の応答形式が不正（upstream_invalid）。",
        503: "上流・認証provider・DB・空き容量が利用不可。Retry-After: 5。",
    }

    def add(
        method,
        path,
        title,
        response,
        tag,
        description="",
        *,
        body=None,
        media="application/json",
        params=(),
        codes=(),
        security=None,
        created=False,
    ):
        admin = path.startswith("/admin/")
        if security is None:
            security = (
                [{"AdminSession": [], **({"AdminCsrf": []} if method != "get" else {})}]
                if admin
                else [{"ViewerSession": []}]
            )
        headers = {"X-Request-ID": {"schema": UUID, "description": "ログ照合用の要求ID。"}}
        success = {
            "description": "成功。" if not created else "同一要求の再送。最初に保存した応答と同じJSON。",
            "headers": headers,
        }
        if response:
            success["content"] = {"application/json": {"schema": ref(response)}}
        auth_labels = {
            "ReplayViewerToken": "クエリ `token`（対象Replayだけの期限付き閲覧トークン）",
            "ViewerSession": "Cookie `jbslq_session`（Viewerログインで発行）",
            "IntegrationBearer": "`Authorization: Bearer <token>`（CLI発行の読取り専用トークン）",
            "AdminSession": "Cookie `jbslq_admin`（管理者ログインで発行）",
            "AdminCsrf": "`X-CSRF-Token: <csrfToken>`（管理ログインまたはmeで取得）",
        }
        authentication = "不要" if not security else " または ".join(
            " ＋ ".join(auth_labels[name] for name in requirement) for requirement in security
        )
        operation = {
            "operationId": title[0],
            "summary": title[1],
            "description": "**認証**: " + authentication + "。\n\n" + description,
            "tags": [tag],
            "security": security,
            "responses": {"200" if response else "204": success},
        }
        if admin:
            operation["servers"] = [{"url": config.admin_public_url.rstrip("/"), "description": "管理画面専用ポート"}]
        if created:
            operation["responses"]["201"] = {**success, "description": "初回の保存に成功。"}
        for code in sorted({400, 403, 500, 503, *codes, *([401, 429] if security else [])}):
            response_headers = {**headers}
            if code in (429, 503):
                response_headers["Retry-After"] = {"schema": {"type": "string", "enum": ["60" if code == 429 else "5"]}}
            operation["responses"][str(code)] = {
                "description": errors[code],
                "headers": response_headers,
                "content": {"application/json": {"schema": ref("Error")}},
            }
        if params:
            operation["parameters"] = list(params)
        if body:
            operation["requestBody"] = {"required": True, "content": {media: {"schema": ref(body)}}}
        document["paths"].setdefault(path, {})[method] = operation
        return operation

    challenge = parameter("challenge_id", UUID, "予約応答のchallengeId。", location="path")
    submission = parameter("submission_id", UUID, "結果応答のsubmissionId。", location="path")
    league = parameter("league_id", LEAGUE, location="path")
    sid = parameter("sid", SID, location="path")
    idem = parameter(
        "Idempotency-Key",
        UUID,
        "同じ要求の再送では同じUUID。結果ではmetadata.clientResultIdと一致。",
        location="header",
        required=True,
    )
    page = [
        parameter("limit", integer(minimum=1, maximum=200, default=50), "最大200件。"),
        parameter("before", integer(maximum=9223372036854775807, default=0), "直前ページのnextCursor。降順。"),
    ]
    auth = add(
        "post",
        "/api/v1/auth/session",
        ("viewerLogin", "ticketを検証してViewerセッションを作成"),
        "PlayerSession",
        "Viewer認証",
        "Content-Typeはapplication/x-www-form-urlencoded。成功時のCookieを以後の要求へ送ります。ticketは認証後に保存しません。",
        body="AuthForm",
        media="application/x-www-form-urlencoded",
        security=[],
        codes=[401, 429],
    )
    auth["responses"]["200"]["headers"]["Set-Cookie"] = {
        "schema": string(),
        "description": "jbslq_session=<opaque>; HttpOnly; Path=/; SameSite=Lax",
    }
    add("get", "/api/v1/auth/me", ("viewerMe", "Viewerセッションを確認"), "PlayerSession", "Viewer認証")
    add(
        "delete",
        "/api/v1/auth/session",
        ("viewerLogout", "Viewerセッションを失効"),
        None,
        "Viewer認証",
        "現在のCookieを失効し、削除用Set-Cookieを返します。",
    )
    add(
        "get",
        "/api/v1/qualifiers/status",
        ("qualifierStatus", "参加資格・譜面・残回数を確認"),
        "QualifierStatus",
        "Challenge",
        "回数は消費しません。上流障害時のstale=trueは参考表示。リーグ不存在も200、reasonCode=league_not_found。残回数0ではeligible=true / attempts_exhaustedになり得ます。",
        params=[
            parameter("leagueId", LEAGUE, required=True),
            *[parameter(key, value, required=True) for key, value in models["MapKey"]["properties"].items()],
        ],
        codes=[422, 502],
    )
    add(
        "post",
        "/api/v1/qualifiers/challenges",
        ("reserveChallenge", "Challengeを予約し1回消費"),
        "Reservation",
        "Challenge",
        "上流の最新資格を確認して予約・回数消費を同時保存します。同一キー・同一内容は保存済み応答を200で返し、追加消費しません。キーの内容変更は409 idempotency_conflict。猶予・タイムアウト・返却条件は予約時に固定。",
        body="ReserveRequest",
        params=[idem],
        codes=[404, 409, 413, 422, 502],
        created=True,
    )
    add(
        "post",
        "/api/v1/qualifiers/challenges/{challenge_id}/started",
        ("startChallenge", "実際のプレイ開始を通知"),
        "Started",
        "Challenge",
        "同じ開始通知の再送は同じstartedAtを返します。異なる通知は409。開始通知が失われても、正当な予約済み結果は提出可能です。",
        body="StartedRequest",
        params=[challenge],
        codes=[404, 409, 422],
    )
    op = add(
        "put",
        "/api/v1/qualifiers/challenges/{challenge_id}/result",
        ("submitResult", "終了結果・Replayを提出または再送"),
        "ResultReceipt",
        "Challenge",
        f"metadataはUTF-8 JSON。ランキング候補のclear / failはgzip BSORが必須です。metadata上限{config.metadata_limit // 1024} KiB、gzip上限{config.compressed_replay_limit // (1024 * 1024)} MiB、展開後{config.expanded_replay_limit // (1024 * 1024)} MiB。"
        "\n\n認証 → 所有者 → 排他取得 → 期限判定 → 本文検証の順です。期限と同時刻は受理、超過は保存済み結果の再送でも409 result_acceptance_expired。"
        "クライアント時刻では延長しません。同じmetadata・未圧縮Replay・キーなら200。内容変更は409。拒否された提出は回数を返却しません。",
        params=[challenge, idem],
        codes=[404, 408, 409, 413, 422],
        created=True,
    )
    op["requestBody"] = {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": obj(
                    {
                        "metadata": ref("ResultMetadata"),
                        "replay": string("ランキング候補は必須。それ以外は条件付き。", format="binary"),
                    },
                    required=["metadata"],
                    closed=True,
                ),
                "encoding": {
                    "metadata": {"contentType": "application/json"},
                    "replay": {"contentType": "application/gzip"},
                },
            }
        },
    }
    bearer = [{"IntegrationBearer": []}]
    add(
        "get",
        "/integration/v1/changes",
        ("scoreChanges", "提出・取消・復元・手動返却の差分を取得"),
        "Changes",
        "jbsl-web連携",
        "seq昇順、submissionはイベント時点のスナップショット。取り込みとnextCursorの保存を同一トランザクションで行います。フィルタごとに別cursorを保持。limit=0は互換動作として1件扱いです。",
        params=[
            parameter("after", integer(maximum=9223372036854775807, default=0)),
            parameter("limit", integer(minimum=0, maximum=500, default=100)),
            parameter("leagueId", LEAGUE),
        ],
        security=bearer,
    )
    add(
        "get",
        "/integration/v1/submissions/{submission_id}",
        ("scoreSubmission", "提出の現在の採否を取得"),
        "SubmissionResponse",
        "jbsl-web連携",
        params=[submission],
        security=bearer,
        codes=[404],
    )
    add(
        "get",
        "/integration/v1/leagues/{league_id}/leaderboard",
        ("scoreLeaderboard", "譜面ごとの現在の自己ベスト・順位を取得"),
        "Leaderboard",
        "jbsl-web連携",
        "effectiveForRanking=trueのみ。SIDとMapKeyごとにmodifiedScore最大を採用。同点自己ベストは受信の早い方、順位は1,1,3。取消時は次点へ戻ります。",
        params=[league],
        security=bearer,
    )
    add(
        "get",
        "/integration/v1/leagues/{league_id}/users/{sid}/attempts",
        ("scoreAttempts", "ユーザー・Leagueごとの回数を取得"),
        "AttemptsResponse",
        "jbsl-web連携",
        "上限・残回数は最後に検証した上流キャッシュに基づき、不明ならnull。",
        params=[league, sid],
        security=bearer,
    )
    login = add(
        "post",
        "/admin/api/login",
        ("adminLogin", "管理者としてログイン"),
        "AdminSession",
        "管理ログイン",
        "JSONとX-JBSL-Admin: 1が必要。IPごとに5要求/分。",
        body="AdminLogin",
        params=[parameter("X-JBSL-Admin", string(const="1"), location="header", required=True)],
        security=[],
        codes=[401, 429],
    )
    login["responses"]["200"]["headers"]["Set-Cookie"] = {
        "schema": string(),
        "description": "jbslq_admin=<opaque>; HttpOnly; Path=/admin; SameSite=Strict",
    }
    add("get", "/admin/api/me", ("adminMe", "管理セッション・CSRFを確認"), "AdminSession", "管理ログイン")
    add("post", "/admin/api/logout", ("adminLogout", "管理セッションを失効"), None, "管理ログイン")
    add(
        "get",
        "/admin/api/state",
        ("adminState", "件数・ディスク・認証設定・バックアップ状態を取得"),
        "Dashboard",
        "管理・閲覧",
    )
    add(
        "get",
        "/admin/api/rankings",
        ("adminRankings", "リーグ・譜面ごとのユーザー最高スコアランキングを取得"),
        "AdminRankings",
        "管理・閲覧",
        "保存済みリーグ一覧と、選択リーグの譜面一覧・有効な自己ベストを返します。"
        "leagueId省略時は記録のある最小IDを選択し、記録なしならleagueIdはnull、各一覧は空です。"
        "取消・対象外を除外しmodifiedScore降順、同点は1,1,3順位。"
        "譜面名・回数上限・曲時間（秒）は保存済みキャッシュを使用し、過去の譜面もハッシュで残します。"
        "残回数はmax(0,上限−現在の未返却使用回数)で、上限不明ならnullです。"
        "表示名がSIDの場合は上流取得時またはログイン時に既存JBSL-WEBランキングの名前で補完します。"
        "閲覧時の上流通信やDB更新は行いません。",
        params=[parameter("leagueId", LEAGUE, "省略時は記録のある最小League ID。")],
        codes=[404],
    )
    add(
        "get",
        "/admin/api/public/rankings",
        ("publicRankings", "ログイン不要のリーグ・譜面別ランキングを取得"),
        "PublicRankings",
        "公開ランキング",
        "[ランキング表示](/admin/rankings/)用の閲覧専用APIです。CookieやCSRFトークンは不要です。"
        "保存済みのリーグ・譜面情報と、順位・表示名・SID・スコア・精度・残回数・提出日時・結果・Replay用リンクを返します。"
        "replayはdownloadUrl・beatleaderUrl・arcviewerUrlを持ち、URLに対象提出IDを含みます。"
        "Replayが存在しない場合はすべてnull、HTTPS未設定なら外部再生URLのみnullです。Challenge ID・管理操作理由は含みません。"
        "集計規則と残回数は管理者ランキングと同じです。leagueId省略時は記録のある最小ID、記録なしは空一覧。"
        "未知のIDは404、不正なIDは400です。正常な閲覧では上流通信・DB更新・セッション作成を行いません。",
        params=[parameter("leagueId", LEAGUE, "省略時は記録のある最小League ID。")],
        codes=[404],
        security=[],
    )
    public_download = add(
        "get", PUBLIC_DOWNLOAD_PATH, ("downloadPublicReplay", "公開ランキングのReplayをダウンロード"),
        None, "公開ランキング",
        "現在ランキングの行に採用されている提出だけを取得できます。Cookie・トークン不要。"
        "取消・対象外・自己ベスト更新で外れた提出、Replay欠落は404 replay_not_found。"
        "公開ReplayのGET / OPTIONSは、両listener合計でIPごと120回/分。Cache-Control: no-store。",
        params=[submission], security=[], codes=[404, 429],
    )
    public_download["responses"]["200"] = {
        **public_download["responses"].pop("204"),
        "description": "保存済みのgzip圧縮BSORファイル。",
        "content": {"application/gzip": {"schema": string(format="binary")}},
        "headers": {"Content-Disposition": {"schema": string(), "description": "attachment; filename=<submissionId>.bsor.gz"}},
    }
    public_params = [submission, parameter("player_id", SID, location="path")]
    public_delivery = add(
        "get", PUBLIC_REPLAY_PATH, ("viewPublicReplay", "公開ランキングの外部再生用BSORを取得"),
        None, "公開ランキング",
        "Cookie・トークン不要。取得時点のランキング採用・Replay存在・SID一致を確認し、不一致は404 replay_not_found。"
        "Originは省略するかhttps://replay.beatleader.comまたはhttps://allpoland.github.ioを指定します。"
        "許可OriginへのCORS応答はCookieを許可しません。公開ReplayのGET / OPTIONS合計でIPごと120回/分。"
        "既存のReplay容量上限でgzipを展開します。ArcViewerはnoProxy=trueを指定します。",
        params=public_params, security=[], codes=[404, 413, 422, 429],
    )
    public_delivery["responses"]["200"] = {
        **public_delivery["responses"].pop("204"),
        "description": "未圧縮BSOR。Cache-Control: no-store。",
        "content": {"application/octet-stream": {"schema": string(format="binary")}},
        "headers": {"Access-Control-Allow-Origin": {"schema": string(), "description": "許可した要求のOrigin。"}},
    }
    add(
        "options", PUBLIC_REPLAY_PATH, ("publicReplayPreflight", "公開ReplayのCORSプリフライト"),
        None, "公開ランキング",
        "Cookie・トークン不要。許可したビューアOriginとAccess-Control-Request-Method: GETが必要。追加要求ヘッダーは不可。"
        "現在のランキング採用・Replay存在・SID一致を確認します。公開ReplayのGET / OPTIONS合計でIPごと120回/分。"
        "成功時204、Access-Control-Allow-Methods: GET。Replay本体は返しません。",
        params=[*public_params, parameter("Origin", string(), location="header", required=True),
                parameter("Access-Control-Request-Method", string(const="GET"), location="header", required=True)],
        security=[], codes=[404, 429],
    )
    add("get", "/admin/api/settings", ("adminSettings", "運用設定とリビジョンを取得"), "Settings", "管理・閲覧")
    add(
        "put",
        "/admin/api/settings",
        ("updateSettings", "運用設定を保存"),
        "Settings",
        "管理・変更",
        "全policy項目と現在のrevisionが必須。古いrevisionは409 settings_conflict。猶予・タイムアウト・返却条件は新しい予約から適用します。",
        body="Settings",
        codes=[409],
    )
    add(
        "get",
        "/admin/api/challenges",
        ("adminChallenges", "Challengeと提出結果を一覧"),
        "ChallengeList",
        "管理・閲覧",
        params=[*page, parameter("sid", SID), parameter("leagueId", LEAGUE), parameter("status", STATUS)],
    )
    add(
        "get",
        "/admin/api/users",
        ("adminUsers", "ユーザーを検索"),
        "UserList",
        "管理・閲覧",
        "SIDまたは表示名の部分一致。SID昇順。limit=0は1件扱い。",
        params=[
            parameter("q", string(maxLength=128, default="")),
            parameter("after", string(default=""), "前ページのnextCursor（SID）。"),
            parameter("limit", integer(maximum=200, default=50)),
        ],
    )
    add(
        "post",
        "/admin/api/challenges/{challenge_id}/force-end",
        ("forceEndChallenge", "進行中のChallengeを強制終了"),
        "ChallengeControl",
        "管理・変更",
        "予約済み・プレイ中をabandoned / admin_force_endedに変更します。理由とrefundAttemptが必須。"
        "refundAttempt=trueなら予約時の自動返却設定にかかわらず同時に1回返却。"
        "結果提出と同じロックで排他し、提出や期限終了が先に確定した場合は409 challenge_state_conflict。"
        "強制終了済みへの再送は200で現在値を返し、返却指定を変更しても追加処理しません。後からの返却は返却APIを使用します。"
        "終了後の開始・提出は409 admin_force_ended（retryable=false）。既存の期限超過判定を優先します。",
        body="ForceEndRequest", params=[challenge], codes=[404, 409],
    )
    add(
        "post",
        "/admin/api/challenges/{challenge_id}/refund",
        ("refundChallenge", "終了済みChallengeの消費1回を手動返却"),
        "ChallengeControl",
        "管理・変更",
        "理由必須。submitted / abandonedの未返却Challengeだけを1回返却し、refundReasonをadmin_manualにします。"
        "自動返却設定には依存しません。スコア・Replay・ランキング採否は保持します。"
        "進行中は409 challenge_state_conflict。返却済みへの再送は200で現在値を返し、理由・回数・履歴を重複更新しません。"
        "提出済みへの返却は、更新したsubmissionのスナップショットをattempt_refunded差分イベントとして記録します。",
        body="RefundRequest", params=[challenge], codes=[404, 409],
    )
    add(
        "get",
        "/admin/api/users/{sid}/attempts",
        ("adminAttempts", "ユーザーの消費・返却・残回数を取得"),
        "Attempts",
        "管理・閲覧",
        params=[sid],
    )
    add(
        "get",
        "/admin/api/audit",
        ("adminAudit", "操作・受信・拒否のログを取得"),
        "AuditList",
        "管理・閲覧",
        "ID降順。limit=0は1件扱い。requestIdをエラーログと照合できます。elapsedMsは受付・操作開始からログ記録までのミリ秒。過去の未計測ログはnullです。",
        params=[
            {**page[0], "schema": integer(maximum=200, default=50)},
            page[1],
            parameter("challengeId", UUID),
            parameter("actor", string()),
        ],
    )
    add(
        "get",
        "/admin/api/submissions/{submission_id}",
        ("adminSubmission", "提出metadata・採否・予約時設定を取得"),
        "SubmissionDetail",
        "管理・閲覧",
        params=[submission],
        codes=[404],
    )
    add(
        "post",
        "/admin/api/submissions/{submission_id}/moderate",
        ("moderateSubmission", "スコアを取消または復元"),
        "Submission",
        "管理・変更",
        "現在のmoderationVersionをversionに送信。競合は409 moderation_conflict。理由必須。回数・元提出・Replayは保持し、採否だけ変更。元々対象外のスコアを復元しても対象外です。",
        body="ModerationRequest",
        params=[submission],
        codes=[404, 409],
    )
    replay = add(
        "get",
        "/admin/api/submissions/{submission_id}/replay",
        ("downloadReplay", "保存済みReplayをダウンロード"),
        None,
        "管理・閲覧",
        params=[submission],
        codes=[404],
    )
    replay["responses"].pop("204")
    replay["responses"]["200"] = {
        "description": "gzip圧縮BSORファイル。",
        "content": {"application/gzip": {"schema": string(format="binary")}},
        "headers": {
            "Content-Disposition": {"schema": string(), "description": "attachment; filename=<submissionId>.bsor.gz"}
        },
    }
    add(
        "post", "/admin/api/submissions/{submission_id}/replay-viewer",
        ("createReplayViewerLink", "外部ビューアの再生URLを発行"), "ReplayViewerLink", "外部Replay再生",
        "API公開URLがHTTPSの場合に利用可能。未設定は409 replay_viewer_unavailable。"
        "管理者ごとに30回/分。URLは対象提出・選択したビューアに限定し、最長10分または管理者セッション期限まで有効。"
        "管理者ログアウト・再ログインで元セッションが失効した場合も利用不可。閲覧用URLをログや第三者へ転載しないでください。",
        body="ReplayViewerRequest", params=[submission], codes=[404, 409],
    )
    delivery_path = "/api/v1/replay-viewer/{submission_id}/{player_id}.bsor"
    delivery_params = [submission, parameter("player_id", SID, location="path")]
    delivery = add(
        "get", delivery_path, ("viewReplay", "外部ビューア用の未圧縮BSORを取得"), None, "外部Replay再生",
        "Cookie不要。トークン不正・期限切れ・対象不一致は401 replay_viewer_token_invalid。"
        "Originを送る場合は発行先ビューアと一致する必要があります。"
        "https://replay.beatleader.com または https://allpoland.github.io のみ許可。"
        "Originなしでもトークンは必須です。IPごと120回/分、トークンごと30回/分。"
        "ArcViewerはnoProxy=trueで直接読み込んでください。",
        params=delivery_params, security=[{"ReplayViewerToken": []}], codes=[404, 413, 422],
    )
    delivery["responses"].pop("204")
    delivery["responses"]["200"] = {
        "description": "未圧縮BSOR。Cache-Control: no-store。",
        "content": {"application/octet-stream": {"schema": string(format="binary")}},
        "headers": {"Access-Control-Allow-Origin": {"schema": string(), "description": "認可した要求のOrigin。"}},
    }
    add(
        "options", delivery_path, ("replayPreflight", "外部Replay読み込みのCORSプリフライト"), None, "外部Replay再生",
        "有効なトークンと発行先Originが必要。Access-Control-Request-Method: GETのみ。追加要求ヘッダーは許可しません。"
        "成功時204、Access-Control-Allow-Methods: GET。Cookieによるクロスオリジン認証は許可しません。",
        params=[*delivery_params, parameter("Origin", string(), location="header", required=True),
                parameter("Access-Control-Request-Method", string(const="GET"), location="header", required=True)],
        security=[{"ReplayViewerToken": []}],
    )
    add(
        "post",
        "/admin/api/backups",
        ("createBackup", "整合性検証付きバックアップを作成"),
        "Backup",
        "管理・変更",
        "Replayと監査履歴を含むDBを保存・検証し、保持数を超えた古いバックアップを削除。ファイル名と検証結果を返します。",
    )
    add(
        "post",
        "/admin/api/leagues/{league_id}/refresh",
        ("refreshLeague", "Leagueキャッシュを再取得"),
        "CacheRefresh",
        "管理・変更",
        "上流に接続して検証済みキャッシュを更新します。",
        params=[league],
        codes=[404, 502],
    )
    add("get", "/healthz", ("health", "プロセスの生存確認"), "Health", "監視", security=[])
    add("get", "/readyz", ("readiness", "DB接続とディスク空き容量の確認"), "Readiness", "監視", security=[])
    return document

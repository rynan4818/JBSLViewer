# API契約

## ブラウザで仕様を確認する

管理用ポートの **`/admin/docs/`** がSwagger UI、**`/admin/openapi.json`** がOpenAPI 3.1文書です。既定は http://127.0.0.1:18763/admin/docs/ 。ログイン前から閲覧でき、Viewer・jbsl-web連携・管理画面・監視の全API操作を掲載しています。接続先URLは起動設定の `api_public_url` と `admin_public_url` に合わせ、管理操作には専用ポートを明記しています。

既存のブラウザ要求制限・認証・CSRFを維持し、Swaggerは閲覧専用です。実行ボタン、資格情報の保存、外部validatorを無効にしています。SwaggerのJS/CSSは同梱しているため、CDNへの接続は不要です。仕様文書には実ユーザー・提出履歴・設定した秘密情報を埋め込みません。

`jbsl_score/documentation.py` と `openapi_schemas.py` に仕様を定義し、実ルートの網羅・主要フローの実応答・設定範囲を `tests/test_documentation.py` で照合します。APIの手動バリデーションは従来どおり実行します。複雑な運用ルールは **`/admin/guide/`** の図付きガイドで確認できます。

## Viewer API

基準はワークスペースの `docs/JBSL_Qualifier_Score_Manager_API_Specification.md` Revision 9と、現行 `JBSLViewer.Qualifier.Core/ScoreManagerApiClient.cs`・`Contracts/StrictJson.cs` です。ルートURLに配置します。ベースパス付きの配置はこのランチャーでは対象外です。

| Method | Path | 認証・要求 |
|---|---|---|
| POST | `/api/v1/auth/session` | `application/x-www-form-urlencoded`: `ticket`, `provider=steamTicket/oculusTicket`, `returnUrl=/` |
| GET | `/api/v1/auth/me` | Cookie `jbslq_session` |
| DELETE | `/api/v1/auth/session` | 同Cookie。成功204 |
| GET | `/api/v1/qualifiers/status` | 同Cookie。query: `leagueId`, `hash`, `characteristic`, `difficulty`, 任意 `jbslRevision` |
| POST | `/api/v1/qualifiers/challenges` | 同Cookie、UUIDの `Idempotency-Key`、JSON予約要求 |
| POST | `/api/v1/qualifiers/challenges/{id}/started` | 同Cookie、JSON開始通知 |
| PUT | `/api/v1/qualifiers/challenges/{id}/result` | 同Cookie、UUIDの `Idempotency-Key`、multipart |

league IDは正の整数、SID・各UUID・revisionは文字列です。MapKeyは40桁SHA-1を大文字へ正規化し、characteristic・difficultyとの3要素で比較します。difficultyの入力 `Expert+` / `Expert Plus` は `ExpertPlus` に正規化します。JSONの重複キー、非有限値、型の暗黙変換を許容しません。

予約要求:

```json
{
  "schemaVersion": 1,
  "leagueId": 3023,
  "map": {
    "hash": "0123456789ABCDEF0123456789ABCDEF01234567",
    "characteristic": "Standard",
    "difficulty": "ExpertPlus"
  },
  "clientVersion": "JBSLViewer/1.0",
  "gameVersion": "1.29.1"
}
```

予約成功201は `schemaVersion`, `challengeId`, `status=reserved`, `attemptNumber`, `attemptLimit`, `remainingAttempts`, `reservedAt`, `resultAcceptUntil`, `map` を返します。同じユーザー・キー・要求の再送は、上流を再取得せず**保存した同じJSONを200**で返します。上流障害等でまだ成功していない予約キーも要求digestを保持し、異なる内容への使い回しを409で拒否します。

開始通知は `schemaVersion=1`, `actualMap`, `gameMode=Solo`, `practice=false`, `submissionAllowed=true`, `startedAtClient` を受け付けます。同じ通知の再送は同じ `startedAt` を返します。開始通知が通信で失われていても、予約済みの正当な結果は受理します。

結果multipartは `metadata` を必須、`replay` を条件付きファイルとします。metadataは既存Viewerの `ResultMetadata` をそのまま送信します。`clientResultId` と結果用 `Idempotency-Key` は一致するUUIDです。予約用キーとは別のキーを生成してください。`clear` / `fail` のランキング候補はgzip BSOR必須、`quit` / `restart` / `unknown` / `preflight_rejected` 等はmetadataのみでも受理します。

gzip上限16 MiB、展開後64 MiB、metadata 64 KiB。BSOR Version 1の全6セクション、数値、UTF-8、配列数、プレイヤーID、プラットフォーム、MapKeyを検証します。ランキング候補ではBSORのscoreをViewerの **`multipliedScore`** と照合し、ゲームバージョンも照合します。`modifiedScore` と `maxPossibleModifiedScore` は整数で、前者が後者を超えないことを確認します。

結果成功201は `schemaVersion`, `submissionId`, `challengeId`, `status=submitted`, `validForRanking`, `invalidReason`, `receivedAt`, `replaySha256`, `remainingAttempts` を返します。未圧縮BSORのSHA-256、正規化metadata、Replayの有無が同じ再送は、保存済みのJSONを200で返します。管理者の取消・復元後もViewer向けの元の受領応答は変えません。現在の採否は連携APIで取得します。

### 受付期限・返却

実効終了日時 `E = qualifier.ends_at ?? end`、予約時の猶予 `G` として、結果受付期限は `E + G` です。認証、所有者確認、challenge排他取得後、**本文の読込み・検証を始める直前**のサーバUTC時刻を受付判定に使います。期限一致は可、超過は保存済み結果の再送でも409 `result_acceptance_expired`。本文の到着と検証には既定60秒の読込み期限・容量上限を適用します。クライアント申告時刻で受付期間を延長しません。

受付中のchallengeは同じOSロックで期限処理から保護されます。予約済み/開始済み・結果未着は期限超過後の保守処理（15秒間隔）で `abandoned` になります。運用タイムアウトは予約からの秒数で、既定0（無効）。有効時は未提出にだけ適用し、受理済み結果の期限内再送には適用しません。受付期限超過の拒否をタイムアウト拒否より優先します。

自動返却は予約時に保存した設定によって行います。形式不正・所有者不一致・Replay不一致などの**拒否された提出では自動返却しません**。`abandoned` の返却を選んだ場合だけ、保守処理の未着確定時に返却します。管理者は自動返却設定とは独立して手動返却でき、1チャレンジにつき自動・手動を合計して最大1回です。返却されても `attemptNumber` は過去を含む通し番号なので再利用しません。残回数は上限から未返却の使用数を引いた値です。

### 現行Viewerとの互換上の調整

リーグ不存在のstatusは `league/map/isParticipant/remainingAttempts=null` ですが、`cache.fetchedAt` は判定時刻を返します。現行Viewerの `StrictJson.ParseStatus` がこの値を非nullの日時として要求するためです。通常の理由優先順位、残回数0時の `eligible=true/reasonCode=attempts_exhausted` は既存契約どおりです。

## JBSL-WEB → スコアサーバの結果取得

管理者がCLIで発行する読取り専用トークンを `Authorization: Bearer <token>` で送ります。ViewerのCookieや管理者Cookieでは利用できません。トークンをURL、クライアントMod、公開JavaScriptへ置かないでください。共通JSONの `schemaVersion=1`、UTC日時、`Cache-Control: no-store` とエラー形式はViewer APIと同じです。

| Method | Path | 内容 |
|---|---|---|
| GET | `/integration/v1/changes?after=0&limit=100` | 提出・取消・復元の増分。任意 `leagueId` |
| GET | `/integration/v1/submissions/{submissionId}` | 現在の提出結果・採否 |
| GET | `/integration/v1/leagues/{leagueId}/leaderboard` | 譜面ごと・ユーザーごとの現在の最高スコア |
| GET | `/integration/v1/leagues/{leagueId}/users/{sid}/attempts` | 譜面ごとの消費・返却・残回数 |

### changes

`after` は直前に処理済みの整数cursor、初回は0。`limit` は1～500、既定100。順序は単調増加する `seq`。結果の保存・取消・復元とイベント生成は同じDBトランザクションです。

```json
{
  "schemaVersion": 1,
  "items": [
    {
      "seq": 1,
      "event": "submitted",
      "occurredAt": "2030-01-01T00:00:00.000Z",
      "submission": {
        "submissionId": "0bbd3bd2-aecd-4d25-b8d2-6eb6b349dfe4",
        "challengeId": "d3c1e6a3-eafc-4a34-b5d8-7c22758883b0",
        "sid": "76561198000000000",
        "leagueId": 3023,
        "map": {"hash": "0123456789ABCDEF0123456789ABCDEF01234567", "characteristic": "Standard", "difficulty": "ExpertPlus"},
        "endType": "clear",
        "modifiedScore": 115,
        "maxPossibleModifiedScore": 115,
        "multipliedScore": 115,
        "missedCount": 0,
        "badCutsCount": 0,
        "goodCutsCount": 1,
        "accuracyPercent": 100.0,
        "validForRanking": true,
        "invalidReason": null,
        "canceled": false,
        "effectiveForRanking": true,
        "moderationVersion": 0,
        "moderationReason": null,
        "receivedAt": "2030-01-01T00:00:00.000Z",
        "replaySha256": "<64桁のSHA-256>",
        "attemptRefunded": false,
        "refundReason": null
      }
    }
  ],
  "nextCursor": 1,
  "hasMore": false,
  "highWatermark": 1
}
```

イベントは `submitted`, `canceled`, `restored`, `attempt_refunded`。`attempt_refunded` は提出済みChallengeの手動返却を表し、`attemptRefunded=true`、`refundReason=admin_manual` の最新submissionを含みます。取り込み側でイベント名を列挙している場合は追加してください。イベント内のsubmissionは**そのイベント時点のスナップショット**です。現在値が必要ならsubmission取得APIを使用します。未提出Challengeの返却は結果の差分に含まず、回数取得APIで確認します。レコードの物理削除は行わないため、差分の取消通知も取りこぼしません。フィルタ付きで消費する場合は、フィルタごとに別cursorを保存します。

jbsl-web側は `submissionId` を一意キーに履歴をupsertし、**同一トランザクションでcursorを保存**してください。例は `integration_client.py` の `ScoreFeed.consume_page()` です。poll間隔は通常5～15秒で十分です。取り込みに失敗したページはcursorを進めず同じページを再取得します。通知先へサーバからHTTPを書き込む方式は使用せず、永続的な差分取得で復旧可能にしています。

### ランキング・既存jbsl-webへの対応

leaderboardは `effectiveForRanking=true` の結果だけを使用し、各ユーザー・3要素MapKey内で `modifiedScore` 最大の結果を採用します。同点の自己ベストは受信が早い方を採用し、同点順位は1,1,3方式です。取消した自己ベストの次点が残っていれば自動的にその結果を採用し、復元時も再計算します。

| 既存jbsl-web側 | スコアサーバ側 |
|---|---|
| `Player.sid` | `submission.sid` |
| `Song` のhash/characteristic/difficulty | `submission.map` の3要素 |
| `League.id` | `submission.leagueId` |
| `Score.score` | 採用結果の `modifiedScore` |
| `Score.acc` | `accuracyPercent`（0～100、最大スコア0の場合null） |
| `Score.miss` | `missedCount + badCutsCount`（未取得のnullは別途未取得扱い） |
| `Score.valid` | `effectiveForRanking` とjbsl-web側の採用判定 |

既存の単一 `Score` 行だけに上書きすると取消時に次点を失うため、提出履歴を別テーブルへ保存するか、更新イベントごとにleaderboardを再取得してください。Qualifier方式に `rawPP` や外部サービスのスコアを流用しません。大会全体のランキング集計・weight等はjbsl-web側で決定します。

## スコアサーバ → JBSL-WEBの資格情報取得

`GET {jbsl_web_url}/leaderboard/api/{leagueId}`、`Accept: application/json`。任意の設定トークンをBearerで送ります。HTTPS、接続3秒・I/O8秒の制限、最大2 MiB、リダイレクトを追わない設定です。

必要項目は `league_id`, `league_title`, `isLive`, `isOpen`, `end`, `qualifier.enabled/submission_method/revision/starts_at/ends_at`, `participants[].sid`, `maps[].hash/characteristic/difficulty/title/qualifier_attempt_limit/song_duration_seconds`。非Qualifierでも完全な形式を返します。`qualifier.enabled=false` のmap上限はnull、trueの上限は1～100。SID・MapKey重複、空revision、不正日時・durationを拒否します。

`participants[].name` は任意の表示情報です。`{"sid":"...","name":"..."}` と従来の `{"sid":"..."}` の両形式を受け付けます。名前が欠けている・空・不正な型などの場合は名前の補完だけを省略し、参加者情報はSIDで検証します。

status用キャッシュは通常60秒以内、上流到達不能時の参考表示は300秒以内。新規予約はTTL/revision hintに関係なく毎回上流を取得します。404はleague不存在、不正応答は502 `upstream_invalid`、到達不能・上流5xx/429は503 `upstream_unavailable`。不正応答を資格なしの正常応答に置換しません。

## 管理画面API・監視

### 外部Replay再生

| ポート | Method | Path | 認証 |
| --- | --- | --- | --- |
| 管理 | POST | `/admin/api/submissions/{submission_id}/replay-viewer` | 管理者Cookie + `X-CSRF-Token` |
| API | GET | `/api/v1/replay-viewer/{submission_id}/{player_id}.bsor?token=...` | 対象Replay専用の閲覧トークン |
| API | OPTIONS | 上記と同じ配信パス・クエリ | 閲覧トークン + 発行先Origin |

発行JSONは `{"viewer":"beatleader"}` または `{"viewer":"arcviewer"}`。成功200で `viewerUrl` とUTCの `expiresAt` を返します。`api_public_url` のHTTPS設定が必要で、HTTP時は409 `replay_viewer_unavailable`。提出詳細の `replayViewerAvailable` で設定の有無を確認できます。この値は配信先や譜面の到達性を保証しません。

閲覧トークンは対象提出・発行元管理者セッション・選択ビューアに限定され、最長600秒または管理者セッション期限まで有効です。ログアウト・セッション置き換え・バックアップ復元後は失効します。不正・期限切れ・提出IDやplayerID不一致は401 `replay_viewer_token_invalid`。Replayなしは404。発行は管理者ごと30回/分、配信はIPごと120回/分・トークンごと30回/分です。

配信応答は未圧縮BSOR、`Content-Type: application/octet-stream`、`Cache-Control: no-store`。保存済みのgzipダウンロードAPIは従来どおりです。Origin付きの要求は、発行先の `https://replay.beatleader.com` または `https://allpoland.github.io` に限定します。Originなしでもトークンは必須です。Cookieや連携Bearerでは代用できません。

OPTIONSは `Origin` と `Access-Control-Request-Method: GET` が必要で、追加要求ヘッダーは許可しません。成功204で `Access-Control-Allow-Methods: GET` と認可したOriginを返します。クロスオリジンCookie認証は許可しません。専用配信パス以外のViewer API・管理APIのOrigin制限は従来どおりです。

BeatLeaderは `?link={URLエンコードした配信URL}`、ArcViewerは `?replayURL={URLエンコードした配信URL}&noProxy=true` で開きます。閲覧URLやtokenをログへ記録しないでください。

### 管理者認証

管理listenerの `/admin/api/*` は、ログイン受付と後述の公開ランキングを除き、独立ログインCookie `jbslq_admin` を使用します。更新には `X-CSRF-Token` が必要です。`GET /admin/api/me` でログイン中ユーザーとCSRFを取得します。ログインはJSON + `X-JBSL-Admin: 1`。Origin照合、CORS不許可、Host検証、HttpOnly、SameSite=Strictを適用します。

設定更新 `PUT /admin/api/settings` は `{revision, policy}`。取消復元 `POST /admin/api/submissions/{id}/moderate` は `{action:"cancel"|"restore", version:<現在のmoderationVersion>, reason:"理由"}`。競合する古い画面からの更新は409で拒否します。最新情報を再取得して操作してください。

`GET /admin/api/rankings?leagueId=3023` は、保存済みの `leagues`（ID・名前）、選択した `leagueId`、`maps`（3要素MapKeyと名前）、`items`（ユーザーごとの有効な最高スコア・順位・表示名・提出情報）を返します。`leagueId` 省略時は記録のある最小ID、リーグ記録がなければ `leagueId:null` と空の一覧を返します。不正なIDは400、記録のないIDは404です。未提出の譜面も `maps` に含み、上流の一覧から外れた過去の譜面も保持します。ランキング規則は連携用leaderboardと同じです。閲覧では上流取得やスコア・回数の更新を行いません。

`maps[].attemptLimit` は最後に検証した上流の回数上限、`maps[].songDurationSeconds` は曲時間（秒）です。取得できない値は `null` となり、画面では `—` を表示します。過去の譜面が現在の上流一覧から外れた場合も同様です。

`items[].remainingAttempts` は `max(0, attemptLimit - budgets.used)` で計算します。SID・リーグ・3要素MapKeyごとの現在の未返却使用回数を参照するため、自己ベスト以外の予約・提出や自動/手動返却も反映します。上限が不明なら `null`、使い切っていれば `0` です。スコアの取消・復元だけでは残回数は変わりません。ランキング・回数・提出状態は同じDB読取スナップショットで取得します。

表示名がSIDと同じ場合は、既存のJBSL-WEB `GET /leaderboard/api/{leagueId}` の `participants[].sid/name` を優先して補完します。名前が得られないSIDは `total_rank[].sid/name`、次に `maps[].scores[].sid/name` を参照します。中継APIのparticipantsは、total_rankに名前があればその名前、それ以外はScoreSaberの名前を返します。名前情報は表示専用としてキャッシュに保存し、上流取得時に既存ユーザーへ反映します。初回ログインでは新しいキャッシュから補完し、SIDを返す再ログインでも補完済みの名前を保持します。SIDと異なる既存表示名をJBSL-WEB名では上書きしません。補完名はユーザー一覧・名前検索・認証済みユーザー情報でも利用します。参加資格の照合は引き続き `participants[].sid` で行います。

既存APIに名前のないSIDは補完できず、SID表示となります。実装前のキャッシュには名前がないため、通常の状態取得・予約、または `POST /admin/api/leagues/{leagueId}/refresh` で上流を再取得すると補完されます。画面の「更新」は保存済み情報を読み直す操作で、追加の上流HTTP要求は行いません。

### 操作・受信ログの所要時間

`GET /admin/api/audit` の `items[].elapsedMs` は、サーバでの受付・操作開始から各イベントのログ記録までの経過ミリ秒（0以上の数値）です。本文受信・上流通信・処理待機を含み、プレイ時間やクライアント側の通信時間は含みません。HTTP要求外の期限処理・バックアップは各操作の開始から計測します。同じ値を `items[].details.elapsedMs` にも保存します。過去の未計測ログは `elapsedMs: null` です。既存DBのテーブル変更は不要です。

API listenerの `/healthz` は生存確認、`/readyz` はDB接続・空き容量確認です。readyは外部provider・jbsl-webの認証情報や稼働を検証するものではありません。管理者の概要画面で上流エラーと認証設定状況を確認できます。

### ログイン不要の公開ランキング

管理listenerの `GET /admin/api/public/rankings?leagueId=3023` は、Cookie・CSRFトークンなしで利用できる閲覧専用APIです。画面は `/admin/rankings/` にあり、ログイン画面の「ランキング表示（ログイン不要）」から開けます。

| 応答項目 | 内容 |
| --- | --- |
| `leagues[]` | `leagueId`、`title` |
| `leagueId` | 選択したリーグID。記録がなければ `null` |
| `maps[]` | `hash`、`characteristic`、`difficulty`、`title`、`attemptLimit`、`songDurationSeconds` |
| `items[]` | `rank`、`sid`、`displayName`、`map`、`modifiedScore`、`accuracyPercent`、`remainingAttempts`、`receivedAt`、`endType`、`replay` |
| `items[].replay` | `downloadUrl`（同じ管理listenerの相対URL）、`beatleaderUrl`、`arcviewerUrl`。Replayなしはすべてnull。HTTPS未設定は外部再生URLのみnull。 |

順位・有効な自己ベスト・残回数は管理者ランキングと同じ保存済みデータから取得します。`leagueId` 省略時は記録のある最小ID、記録なしは空一覧、不正なIDは400、未知のIDは404です。Replay用URLには対象提出IDを含みます。Challenge ID・取消/返却理由・操作バージョンは含めません。

正常な閲覧では上流通信・DB更新・セッション作成を行いません。Host・Origin検証は管理listenerの設定を使用し、Viewer APIポートでは配信しません。公開APIはGETのみ受け付けます。既存の管理APIには引き続き管理者認証と、変更時のCSRFトークンが必要です。

### 公開ランキングのReplay取得・再生

| listener | メソッド・パス | 内容 |
| --- | --- | --- |
| 管理 | `GET /admin/api/public/submissions/{submission_id}/replay` | 保存済みgzipを `application/gzip`、添付名 `{submission_id}.bsor.gz` で返す。 |
| API | `GET /api/v1/public/replays/{submission_id}/{player_id}.bsor` | 外部ビューア用の未圧縮BSORを `application/octet-stream` で返す。 |
| API | 同BSORパスの `OPTIONS` | 許可OriginからのGETプリフライトに204を返す。 |

Cookie・CSRF・閲覧トークンは不要です。取得時点でランキングに採用されている提出だけを配信します。ランキング採用とReplay読取は同じDBスナップショットで確認し、取消・対象外・自己ベスト更新で外れた提出・Replay欠落・SID不一致は404 `replay_not_found`。同点の別提出を含め、表示された提出から別のプレイへリダイレクトしません。画面を再読み込みすると最新のリンクになります。

公開ReplayのGET / OPTIONSには両listener合計でIPごと120回/分の制限があり、超過は429（`Retry-After: 60`）です。要求数制限とエラー監査ではDBに記録しますが、スコア・回数・セッション・閲覧トークンは変更しません。BSOR展開には既存の圧縮・展開サイズ上限を適用します。配信は `Cache-Control: no-store`。

CORSはBSOR専用パスのGET / OPTIONSと、`https://replay.beatleader.com`・`https://allpoland.github.io` に限定し、Cookieを許可しません。OriginなしのGETも利用できます。プリフライトは `Access-Control-Request-Method: GET`、追加要求ヘッダーなしが必要です。外部再生URLはHTTPS設定時に生成し、BeatLeaderに `link`、ArcViewerに `replayURL` と `noProxy=true` を指定します。

公開画面のリプレイ列には小さな `DL`・`BeatLeader`・`ArcViewer` の3操作を横並びで表示します。リーグ・譜面は選択欄で切り替え、最新の保存済みランキングはブラウザの再読み込みで取得します。

### 強制終了・手動返却

| API | 要求JSON | 対象 |
| --- | --- | --- |
| `POST /admin/api/challenges/{challenge_id}/force-end` | `{"reason":"通信障害のため","refundAttempt":false}` | 予約済み・プレイ中。`refundAttempt=true` なら同時に1回返却 |
| `POST /admin/api/challenges/{challenge_id}/refund` | `{"reason":"運営判断による再挑戦"}` | 提出済み・未提出終了の消費1回を返却 |

管理者認証・CSRFが必須です。UUID、JSONの項目・型、前後の空白を除いて1～500文字の理由を検証します。成功時は200で `{challengeId,status,abandonedReason,attemptRefunded,refundReason}` を返します。存在しないIDは404、不正入力は400、対象外の状態は409 `challenge_state_conflict` です。

強制終了は `abandoned` / `admin_force_ended` として保存します。結果提出と同じロックで排他するため、提出が先に確定していた場合は強制終了を拒否します。強制終了後の開始・提出は409 `admin_force_ended`、`retryable=false` になります。既存の期限超過判定はこれより優先します。返却なしで強制終了した場合は、後からの保守処理でも自動返却しません。

強制終了済みへの再送は200で現在値を返し、返却指定を変えても追加処理しません。後から返却するには返却APIを使用してください。返却済みへの返却再送も200で、最初の理由と回数・履歴を維持します。返却は自動・手動を合計して1Challengeにつき最大1回です。手動返却の `refundReason` は `admin_manual` です。

提出済みの元結果・Replay・ランキング採否、予約・結果の再送用受領応答は書き換えません。最新の残回数はViewer status・管理者・連携の回数APIから取得してください。提出済みへの手動返却は `attempt_refunded` 差分も同時に保存します。

エラーは `{error:{code,message,retryable,requestId,details}}`。429は `Retry-After: 60`、503は `Retry-After: 5`。クライアントは同じpayloadと同じキーを維持して再試行します。上流/providerの実資格情報を使う本番疎通は、本番接続先の運用者が設定した後に確認してください。

# JBSL Qualifier スコア管理サーバ API仕様書

## 0. 文書情報と実装基準

| 項目 | 内容 |
|---|---|
| API版 | Version 1 / schemaVersion = 1 |
| 作成日 | 2026-09-06 |
| 最終改訂 | 2026-09-13 |
| 改訂 | Revision 10。指定された完成版ソースに合わせて実装仕様へ更新 |
| 基準実装 | mock_servers/score_manager |
| 利用クライアント | JBSLViewer/JBSLViewer、JBSLViewer/JBSLViewer.Qualifier.Core |
| ステータス | ソースコード照合済み。今回の改訂は文書更新であり、実機・公開環境の稼働保証を意味しない |

本書は指定された仮スコア管理サーバの実際のAPI・保存処理を記述する。通常起動はstub認証を使うTEST ONLYサーバである。別実装のscore_serverやJBSLViewer/server内の配布用コピーの機能を、このフォルダの機能として扱わない。

旧版の本番向け実装計画、推奨データモデル、未実装チェックリストを実装記述へ置き換えた。スコア再計算や公開ランキングは、この仮サーバの実装範囲に含まれていない。

関連文書:

- [全体設計](JBSL_Qualifier_Design_For_GPT-5.6Sol.md)
- [JBSL-WEB中継API仕様](JBSL_WEB_Qualifier_API_Specification.md)

主な根拠:

| 内容 | ソース |
|---|---|
| HTTP、認証、status、予約、結果、期限 | [score_manager_server.py](../server/mock_servers/score_manager/score_manager_server.py) |
| SQLite schema | [database.py](../server/mock_servers/score_manager/database.py) |
| MapKey・leaderboard検証 | [schemas.py](../server/mock_servers/score_manager/schemas.py) |
| 上流取得・エラー変換 | [jbsl_client.py](../server/mock_servers/score_manager/jbsl_client.py) |
| BSOR構造検証 | [bsor_reader.py](../server/mock_servers/score_manager/bsor_reader.py) |
| 通常起動設定・管理API | [control.py](../server/mock_servers/score_manager/control.py)、[admin_server.py](../server/mock_servers/score_manager/admin_server.py) |
| クライアントの送信処理 | [ScoreManagerApiClient.cs](../JBSLViewer.Qualifier.Core/ScoreManagerApiClient.cs) |

## 1. 責務と信頼境界

仮サーバは、Cookieで特定したユーザーのSIDと、サーバ自身が取得したleaderboardを照合する。Viewerのローカル判定、自己申告のSID、jbslRevisionを認可の証明にしない。

管理単位は「ユーザー × leagueId × hash × characteristic × difficulty」。予約が成功した時点で1回消費し、Play開始失敗、Fail、Quit、Restart、期限切れ、提出拒否でも自動返却しない。正常なスコア行を回数台帳の代用にしない。

予約成功後のstartedとresultは、現在の選択譜面や最新の参加者一覧を再確認せず、既存challengeの所有者・状態を確認する回復通信である。resultはさらに保存済み受付期限を確認する。

## 2. 接続と共通データ

通常起動のAPIは http://127.0.0.1:18082、管理画面は http://127.0.0.1:18765/admin/。上流の既定値は http://127.0.0.1:18080。

| 項目 | 実装規約 |
|---|---|
| JSON | APIの要求・応答はcamelCase。上流leaderboardは既存のsnake_case等を維持 |
| schemaVersion | JSON整数1。文字列やboolは不可 |
| leagueId | 予約bodyでは正のJSON整数。status queryでは先頭0のない正の10進文字列 |
| SID | 文字列で完全一致。数値化や大小文字変換をしない |
| UUID | challengeId、clientResultId、Idempotency-Key。Viewerは標準UUID表記を生成 |
| MapKey | hash、characteristic、difficultyの3項目。score APIのMapKey要求は余分な項目を拒否 |
| hash | 前後空白除去・大文字化後の40桁16進文字列 |
| difficulty | Easy / Normal / Hard / Expert / ExpertPlus。Expert+、Expert PlusをExpertPlusへ正規化 |
| characteristic | 空でない文字列。大小文字を含め完全一致 |
| 時刻 | サーバ生成値はUTCのISO 8601、ミリ秒とZ付き。Python入力はoffset付き日時も受理 |
| null | 未取得値を0で代用せずnullにする。必須キーの省略とは異なる |

Viewerの日時パーサーはZまたは+00:00だけを受理するため、連携JSONはUTCで統一する。Pythonが受理するすべての日時表記をViewerが受理するわけではない。

score APIはCookie認証であり、Bearerトークン、X-Attempt-Token、CSRFトークンを使わない。セッションCookieはメモリ内CookieContainerで扱い、Outboxへ保存しない。

共通応答にはCache-Control: no-store、X-JBSL-Mock-Server: true、X-Request-IDを付ける。一般例外は500 internal_error。業務例外は次の形式を使う。フレームワークのルーティング・型検証エラーはこの形式と異なる場合がある。

~~~json
{
  "error": {
    "code": "attempts_exhausted",
    "message": "No qualifier attempts remain.",
    "retryable": false,
    "requestId": "f1cc6c68-7b89-4f9a-bb9e-4234180c489a",
    "details": {}
  }
}
~~~

## 3. API一覧

| Method | Path | 認証 | Idempotency-Key | 成功 |
|---|---|---|---|---|
| POST | /api/v1/auth/session | platform ticket | 不要 | 200 |
| GET | /api/v1/auth/me | Cookie | 不要 | 200 |
| DELETE | /api/v1/auth/session | Cookie | 不要 | 204 |
| GET | /api/v1/qualifiers/status | Cookie | 不要 | 200 |
| POST | /api/v1/qualifiers/challenges | Cookie | 必須 | 新規201、成功済み再送200 |
| POST | /api/v1/qualifiers/challenges/{challengeId}/started | Cookie | 不要 | 200 |
| PUT | /api/v1/qualifiers/challenges/{challengeId}/result | Cookie | 必須 | 新規201、同一結果200 |
| GET | /healthz | 不要 | 不要 | DB確認 |
| GET | /__mock__/state | 不要 | 不要 | 検証用状態 |
| GET | /docs、/openapi.json | 不要 | 不要 | API資料 |

Hostは127.0.0.1、localhost、テスト用testserverに限定する。HTTPはallow_insecure_loopback_cookieがtrueの場合だけ受理する。通常のrun.py起動ではこの開発用設定を有効にする。汎用create_app(Settings.from_env())の既定はfalseなので、起動経路を区別する。

## 4. 認証API

### 4.1. POST /api/v1/auth/session

application/x-www-form-urlencodedで送信する。

| 項目 | 条件 |
|---|---|
| ticket | 文字列、8192文字以下。空値は認証処理で拒否 |
| provider | steamTicket / oculusTicket |
| returnUrl | "/"のみ。省略時も"/" |

成功例のSID・日時は説明用の架空値である。

~~~json
{
  "schemaVersion": 1,
  "authenticated": true,
  "user": {
    "sid": "76561198000000000",
    "displayName": "JBSL Test Player"
  },
  "expiresAt": "2026-09-14T00:00:00.000Z",
  "testOnly": true
}
~~~

Cookie名はjbslq_session。Path=/、HttpOnly、SameSite=Lax。開発HTTPを許可しない設定ではSecureを付ける。Cookieに永続化用Max-Ageは設定せず、DBのexpires_atで有効期限を管理する。既定セッション寿命は43,200秒（12時間）、固定期限である。

ランダムなセッション値のSHA-256だけをsessions.id_hashへ保存する。再認証時にはusers.sidで既存ユーザーを再利用するため、同じSIDの回数台帳は引き継がれる。

認証モード:

- stub: 空文字と文字列invalid以外のticketを受理し、設定済みstub_sidを返す。ticketの本人確認は行わない。
- real-provider-test: Steamは設定先のAuthenticateUserTicket/v1へappid=620980を付けて問い合わせ、Oculusは設定先へBearer ticketとfields=id,nameを送る。これは外部providerへの通信方式であり、Viewer→仮サーバはCookieのままである。
- real-provider-testの設定欠落、通信障害、不正provider応答はauth_provider_unavailable等で失敗する。必要な接続先とSteam API keyは環境変数で与え、文書・ログへ実値を書かない。

Viewerは認証応答のuser.sidと現在のplatformUserIdを照合する。stub_sidも実際のテストユーザーと一致させる必要がある。

### 4.2. GET /api/v1/auth/me / DELETE /api/v1/auth/session

GETはschemaVersion、authenticated、user、expiresAtを返す。auth/sessionのtestOnly追加項目はGET応答にはない。DELETEは当該セッションを失効させ、Cookieを削除して204を返す。

未認証、失効済み、現在時刻がexpires_at以上のセッションは401 authentication_required。各認証済み呼出しでlast_seen_atを更新するが、expires_atを延長しない。

## 5. GET /api/v1/qualifiers/status

~~~http
GET /api/v1/qualifiers/status?leagueId=3023&hash=0123456789ABCDEF0123456789ABCDEF01234567&characteristic=Standard&difficulty=ExpertPlus&jbslRevision=42
Cookie: jbslq_session=<session>
~~~

leagueIdとMapKeyの3項目は必須。jbslRevisionはViewerが送る参照値だが、仮サーバでは判定・cache強制更新に使用しない。

~~~json
{
  "schemaVersion": 1,
  "serverTime": "2026-09-13T12:00:00.000Z",
  "eligible": true,
  "reasonCode": "eligible",
  "league": {
    "id": 3023,
    "name": "Example Qualifier",
    "submissionMethod": "jbsl_qualifier_v1",
    "revision": "42"
  },
  "map": {
    "hash": "0123456789ABCDEF0123456789ABCDEF01234567",
    "characteristic": "Standard",
    "difficulty": "ExpertPlus",
    "title": "Example Song",
    "attemptLimit": 3,
    "attemptScope": "per_player_per_map"
  },
  "isParticipant": true,
  "remainingAttempts": 3,
  "cache": {
    "fetchedAt": "2026-09-13T12:00:00.000Z",
    "stale": false
  }
}
~~~

判定順序は次のとおり。

| 優先順 | reasonCode | 条件 |
|---|---|---|
| 1 | league_not_found | 上流404 |
| 2 | qualifier_disabled | qualifier.enabled=false |
| 3 | wrong_submission_method | submission_methodがjbsl_qualifier_v1以外 |
| 4 | league_not_open | isLiveまたはisOpenがfalse |
| 5 | outside_qualifier_window | 開始前、または開始期限超過 |
| 6 | map_not_found | MapKeyが存在しない |
| 7 | not_participant | 認証SIDがparticipantsに存在しない |
| 8 | eligible | 上記に該当しない |

eligibleは回数とは別の資格判定値である。回数0ではeligible=trueのままreasonCode=attempts_exhaustedになる。stale表示では元のeligibleを維持し、reasonCode=upstream_unavailable、cache.stale=trueとする。開始可否はeligibleだけで決めず、reasonCode、残回数、staleも確認する。

league_not_found時はleague、map、isParticipant、remainingAttempts、cache.fetchedAtをnullとし、cache.stale=falseを返す。その他ではleague情報を返し、mapは存在する場合だけ返す。isParticipantはSID照合結果である。

remainingAttemptsを計算するのは、譜面と上限が存在し、元のreasonCodeがeligible / league_not_open / outside_qualifier_windowの場合だけ。優先順位上、期間外かつ非参加者でもこの回数計算へ進み得る。その他はnullである。

### 5.1. 上流cache

cacheキーはleagueIdで、保存したsource_urlが現在の上流URLと一致する場合だけ再利用する。

- 取得後60秒以内はfreshとして再利用する。
- 期限超過または未取得時は上流を取得し、projectionを検証して保存する。
- upstream_unavailable時だけ、取得後300秒以内の既存cacheをHTTP 200の参考表示に使用する。
- 不正JSON・schemaは502 upstream_invalidとして返し、古い値や対象外扱いへ置き換えない。
- 300秒を超える到達不能は503。上流404は200のleague_not_found応答へ変換する。
- 上流の400/409は502 upstream_invalid、500以上は503 upstream_unavailable。中継自身が502を返した場合も、この変換規則に従い503になる。

## 6. POST /api/v1/qualifiers/challenges

~~~json
{
  "schemaVersion": 1,
  "leagueId": 3023,
  "map": {
    "hash": "0123456789ABCDEF0123456789ABCDEF01234567",
    "characteristic": "Standard",
    "difficulty": "ExpertPlus"
  },
  "clientVersion": "JBSLViewer/0.4.0",
  "gameVersion": "1.39.1"
}
~~~

上記5キーを必須とし、余分なルートキーを拒否する。clientVersionとgameVersionは空でない文字列。Idempotency-Keyには確認操作ごとに生成したUUIDを送る。

~~~json
{
  "schemaVersion": 1,
  "challengeId": "f3b8e10d-e24a-4c26-bdf0-a9e3c27a51d5",
  "status": "reserved",
  "attemptNumber": 1,
  "attemptLimit": 3,
  "remainingAttempts": 2,
  "reservedAt": "2026-09-13T12:00:01.000Z",
  "resultAcceptUntil": "2026-09-13T13:05:00.000Z",
  "map": {
    "hash": "0123456789ABCDEF0123456789ABCDEF01234567",
    "characteristic": "Standard",
    "difficulty": "ExpertPlus"
  }
}
~~~

### 6.1. 排他と冪等性

1. MapKey等を正規化した要求のcanonical JSONをSHA-256化する。
2. user_idとIdempotency-Keyを主キーとするreservation_requestsへpendingを登録する。別内容で同じキーを使用すると409 idempotency_conflict。
3. BEGIN IMMEDIATEで書込みロックを取得する。成功済み要求なら保存されたresponse_jsonを200で返す。
4. 新規・未成功要求はロックを保持したまま上流を同期取得する。TTLやrevisionにかかわらず最新の資格・上限を再確認する。
5. 現在の上限とused_attemptsを照合し、1回加算、challenge作成、成功応答snapshot、cache、監査イベントを同一トランザクションでcommitする。
6. 上流取得・資格・回数チェックで失敗した場合は消費をrollbackする。先に登録したpending要求は残り、同じキー・内容で再試行できる。

成功済みの再送は、後から上限や参加者、期間、消費回数が変わっても最初の応答を返す。上流再取得や追加消費はしない。未解決予約の自動再送では新しいキーを生成しない。

SQLiteの書込みロックは同じDB全体に及び、上流通信中も保持する。別キーの同時予約も直列化されるが、サーバは「同一ユーザーに進行中challengeは1件だけ」という制約を持たない。新規挑戦のUI側排他はViewerが担当する。

## 7. 開始期限と結果受付期限

| 項目 | 計算・判定 |
|---|---|
| effectiveEnd | qualifier.ends_atがあればその値、なければleague.end |
| 開始日時 | starts_atがnullなら下限なし。now < starts_atを拒否 |
| サーバ既定開始期限 | now <= effectiveEnd |
| 任意の開始期限profile | effective_end_minus_song_durationなら、曲時間がある譜面はeffectiveEndからその秒数を引く。nullなら引かない |
| Viewerの開始期限 | now <= effectiveEnd - ローカルsongDuration。速度倍率・Pause予定時間を補正に使わない |
| resultAcceptUntil | 予約時のeffectiveEnd + result_grace_seconds。既定300秒。challengeに固定保存 |
| 結果受信時刻 | resultハンドラー入口。認証・body読取り・BSOR検証完了時刻ではない |
| 期限ちょうど | 既定は受理。result_deadline_equal_is_accepted=falseで期限以上を拒否 |
| 任意timeout | receivedAt >= reservedAt + challenge_timeout_secondsなら拒否。既定null |

予約では上流取得後に時計を読み直して開始可否を判断する。resultでは受信時刻で判定し、処理中に壁時計上の期限を越えても、そのことだけで拒否しない。

結果期限の判定は重複結果の照合より先である。したがって保存済み結果の完全同一再送でも、期限後は409 result_acceptance_expiredになる。受付期間中の無制限な再送保証と、永久に再取得できる保証を混同しない。

## 8. POST /api/v1/qualifiers/challenges/{challengeId}/started

~~~json
{
  "schemaVersion": 1,
  "actualMap": {
    "hash": "0123456789ABCDEF0123456789ABCDEF01234567",
    "characteristic": "Standard",
    "difficulty": "ExpertPlus"
  },
  "gameMode": "Solo",
  "practice": false,
  "submissionAllowed": true,
  "startedAtClient": "2026-09-13T12:00:03.000Z"
}
~~~

6キーを必須とし、余分なルートキーを拒否する。gameMode=Solo、practice=false、submissionAllowed=trueが必要。actualMapは予約MapKeyと一致させる。

~~~json
{
  "schemaVersion": 1,
  "challengeId": "f3b8e10d-e24a-4c26-bdf0-a9e3c27a51d5",
  "status": "started",
  "startedAt": "2026-09-13T12:00:03.000Z"
}
~~~

reserved→startedへ遷移する。同じ正規化要求の再送は最初のstartedAtを返し、別内容は409 challenge_state_conflict。所有者違いは403、存在しないchallengeは404、MapKey不一致は422 replay_mismatch。

startedでは回数を追加消費せず、上流・開始期限・結果期限・任意timeoutも再判定しない。Viewerは開始通知の失敗を理由に実Gameplayを取り消さない。通知未着でもreservedのままresultを提出できる。

## 9. PUT /api/v1/qualifiers/challenges/{challengeId}/result

### 9.1. 搬送形式

multipart/form-dataでmetadataを1個、replayを最大1個送る。他のpart名や重複metadataは拒否する。

- metadata: UTF-8 JSON。テキストpartとファイルpartを受理する。
- replay: gzipで圧縮したBSOR Version 1のファイルpart。Viewerはapplication/gzip、replay.bsor.gzとして送る。
- Idempotency-Key: metadata.clientResultIdと同じUUID。
- pathのchallengeId: metadata.challengeIdと一致。
- ファイル名を保存先として使用しない。

metadataの完全な例:

~~~json
{
  "schemaVersion": 1,
  "clientResultId": "aab83144-4fd6-45ab-9f2c-209be5c5a14d",
  "challengeId": "f3b8e10d-e24a-4c26-bdf0-a9e3c27a51d5",
  "map": {
    "hash": "0123456789ABCDEF0123456789ABCDEF01234567",
    "characteristic": "Standard",
    "difficulty": "ExpertPlus"
  },
  "endState": "cleared",
  "endAction": "none",
  "endType": "clear",
  "endSongTime": 120.0,
  "multipliedScore": 100000,
  "modifiedScore": 100000,
  "maxPossibleModifiedScore": 115000,
  "missedCount": 0,
  "badCutsCount": 0,
  "goodCutsCount": 100,
  "maxCombo": 100,
  "fullCombo": true,
  "energy": 0.8,
  "modifiers": [],
  "submissionEligibility": {
    "allowedAtStart": true,
    "remainedAllowed": true,
    "blockers": []
  },
  "scoreValidity": {
    "validForRanking": true,
    "invalidReason": null,
    "restartDetected": false,
    "playInstanceCount": 1
  },
  "timing": {
    "confirmedAtClient": "2026-09-13T12:00:00.000Z",
    "reserveResponseReceivedAtClient": "2026-09-13T12:00:01.000Z",
    "startedAtClient": "2026-09-13T12:00:03.000Z",
    "endedAtClient": "2026-09-13T12:02:03.000Z",
    "resultFinalizedAtClient": "2026-09-13T12:02:04.000Z",
    "localSongDurationSeconds": 120.0,
    "songSpeedMultiplier": 1.0,
    "totalPauseSeconds": 0.0
  },
  "clientVersion": "JBSLViewer/0.4.0",
  "gameVersion": "1.39.1",
  "diagnostics": {
    "failureCode": null,
    "actualMap": null,
    "replayGenerationFailed": false
  }
}
~~~

diagnostics以外のルートキーはすべて必須。未知のルートキーは拒否する。上記はmetadataの例であり、この採用候補には別途replay partが必要である。

### 9.2. 型・終了理由

スコア・件数・maxComboは0以上の整数またはnull。endSongTimeは0以上の有限数またはnull。energyは有限数またはnullであり、この実装では0〜1の範囲検証までは行わない。fullComboはboolまたはnull、modifiersは文字列配列またはnull。

submissionEligibilityはallowedAtStart、remainedAllowed、blockersだけを持つ。前2項目はbool、blockersは文字列配列。allowedAtStart=falseかつremainedAllowed=trueは不正。

scoreValidityはvalidForRanking、invalidReason、restartDetected、playInstanceCountだけを持つ。playInstanceCountは整数0または1。

| endType | endState | endAction | 主なinvalidReason | 採用候補 |
|---|---|---|---|---|
| clear | cleared | none | null / submission_disabled / replay_unavailable | 条件を満たせば可 |
| fail | failed | none | null / submission_disabled / replay_unavailable | 条件を満たせば可 |
| quit | incomplete | quit | quit | 不可 |
| restart | incomplete | restart | restarted | 不可 |
| unknown | unknown | unknown | unknown | 不可 |
| preflight_rejected | incomplete | none | preflight_rejected | 不可 |

clear/failでは提出禁止をreplay不足より優先する。採用候補はallowedAtStart=true、remainedAllowed=true、restartDetected=false、playInstanceCount=1、invalidReason=nullとする。restartはrestartDetected=true、playInstanceCount=1が必要。

timingは例の8キーを必須とし、各値をnullにできる。日時の前後関係や実プレイ時間との一致は検証しない。曲時間と速度は有限の正数、Pause合計は有限の0以上。preflight_rejectedではplayInstanceCount=0ならstartedAtClient=null、1なら非nullにする。

diagnosticsは省略・null・objectを許す。objectの許可キーはfailureCode、actualMap、replayGenerationFailedのみ。failureCodeは文字列またはnull、actualMapはMapKeyまたはnull、replayGenerationFailedはboolまたはnull。

### 9.3. BSORと採用範囲

既定のbsor_score_validation_profileはbasic_identity_onlyで、この実装で選択可能な唯一のprofileである。

| 検証 | 実装 |
|---|---|
| gzip | 解凍可能でサイズ上限以内 |
| header | magic=0x442D3D69、version=1 |
| section | 0 Info → 1 Frames → 2 Notes → 3 Walls → 4 Heights → 5 Pausesを各1回、順番どおり必須 |
| 基本型 | 切詰め、未知section、重複section、不正UTF-8、非有限float、不正boolを拒否 |
| 上限 | 文字列64 KiB、各配列2,000,000要素 |
| 識別 | playerID=認証SID、platform=認証provider対応値、hash/mode/difficulty=予約MapKey |
| SHA-256 | gzipではなく展開後BSOR全体から計算 |
| スコア再計算 | 行わない |
| スコア・modifier・gameVersion・時刻等の相互照合 | このprofileでは行わない |

Steamのplatform許可値はsteam / Steam。Oculusはoculus / Oculus / oculuspc / OculusPC。

clear/failかつvalidForRanking=trueではBSORを必須とする。replay_unavailableを宣言した結果にBSORを添付することはできない。他の無効結果はBSORなしでも受理するが、添付したBSORは同じ構造・識別検証を受ける。

validForRankingはmetadataの整合性検証後の申告値を保存する。この仮サーバによる本格的な不正対策やゲームスコア再計算の証明ではない。ランキング集計、最高スコア選択、公開Replay配信APIは実装していない。

### 9.4. サイズと保存順序

既定上限は圧縮replay 16 MiB、展開後128 MiB、metadata 512 KiB。multipart全体は「圧縮上限 + metadata上限 + 1 MiB」。Content-Lengthがない場合も読取量を制限する。管理設定で上限を変更できるが、Viewerの圧縮replay上限は16 MiBのままである。

resultはBEGIN IMMEDIATE取得後、所有者と期限を検証し、ロックを保持してbodyを読み取る。BSORを検証した後、ランダム名の一時ファイルへ展開後のバイト列を書き込み、flush/fsyncし、submissionId.bsorへ移動する。結果、応答snapshot、replay_blobs、submitted状態、監査をcommitする。例外時はrollbackとファイル削除を試みる。DBとファイルシステムを単一トランザクションで原子的にcommitする実装ではない。

~~~json
{
  "schemaVersion": 1,
  "submissionId": "d06ca383-1d31-48d9-a8c2-a9f5f0a4767e",
  "challengeId": "f3b8e10d-e24a-4c26-bdf0-a9e3c27a51d5",
  "status": "submitted",
  "validForRanking": true,
  "invalidReason": null,
  "receivedAt": "2026-09-13T12:02:05.000Z",
  "replaySha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "remainingAttempts": 2
}
~~~

同一challengeId・clientResultId、同じ正規化metadata、同じ展開後BSOR SHA-256なら、最初の応答JSONを200で返す。新規保存は201。残回数等を再生成しない。別結果との衝突はresult_conflictまたはidempotency_conflictとなり、上書きしない。

## 10. 状態・保存モデル

~~~mermaid
stateDiagram-v2
    [*] --> reserved: 予約成功・1回消費
    reserved --> started: 開始通知
    reserved --> submitted: 結果受理
    started --> submitted: 結果受理
    reserved --> abandoned: 期限処理
    started --> abandoned: 期限処理
~~~

submittedには採用対象外の結果も含む。abandoned化はresult受付の期限チェックや/__mock__/state取得で行う。独立した定期バックグラウンド掃除処理を保証しない。管理画面のInspectorは期限超過表示と保存済みstatusを分け、閲覧によってDBを変更しない。

| テーブル | 保存内容・一意性 |
|---|---|
| users | id、UNIQUE sid、display_name、作成・更新時刻 |
| sessions | tokenのSHA-256、user_id、provider、有効期限、失効日時 |
| league_qualifier_caches | league_id主キー、projection、revision、source_url、取得時刻 |
| attempt_budgets | user_id/league_id/MapKey複合主キー、attempt_limit、used_attempts、version |
| reservation_requests | user_id/key複合主キー、digest、pending/succeeded、challenge、最初の応答JSON |
| challenges | UUID、所有者、MapKey、予約時revision・上限・番号・期限、状態、started要求 |
| results | challenge_idとclient_result_idがそれぞれUNIQUE、metadata、応答JSON、採否、replay情報 |
| replay_blobs | result_id主キー、保存先、展開後サイズ・SHA-256 |
| audit_events | 認証、予約、開始、提出、重複提出、拒否のイベント |

SQLiteはWAL、foreign_keys=ON、busy_timeout既定30秒。最新上限はstatusで表示計算し、予約時にbudgetへ反映する。上限を下げてもused_attemptsは消さず、残数はmax(0, limit - used)とする。

## 11. エラーと再送

| HTTP | code | 主な発生条件 |
|---|---|---|
| 400 / 422 | malformed_request | JSON、型、日時、組合せ不正。処理段階によりstatusが異なる |
| 401 | invalid_ticket / authentication_required | ticket拒否、未認証・期限切れ |
| 403 | qualifier_disabled / wrong_submission_method / league_not_open / outside_qualifier_window / not_participant | 予約の資格不一致 |
| 403 | challenge_owner_mismatch | 他ユーザーのchallenge |
| 404 | league_not_found / map_not_found / challenge_not_found | 予約対象・challengeなし |
| 409 | attempts_exhausted / idempotency_conflict / result_conflict / challenge_state_conflict | 回数・冪等性・状態競合 |
| 409 | result_acceptance_expired / challenge_timed_out | 結果期限超過 |
| 413 | replay_too_large / malformed_request | replay・multipart / metadataサイズ超過 |
| 422 | replay_invalid / replay_mismatch | BSOR不正 / 識別不一致 |
| 422 | map_not_found / challenge_state_conflict | MapKey要求形式不正 / startedのSolo・practice・submission条件不正 |
| 429 | rate_limited | 制限超過。Retry-After: 60 |
| 502 | upstream_invalid | 上流応答不正 |
| 503 | upstream_unavailable / auth_provider_unavailable | 上流・provider障害 |
| 500 | internal_error | 予期しない例外 |

retryable=trueの既定はauth_provider_unavailable、upstream_unavailable、upstream_invalid、rate_limited、internal_error。Viewerは401で同一所有者・同一接続先の再認証を最大1回試し、その後は認証待ちとする。結果の恒久エラーと期限超過はstoppedとして保持する。HTTP再送は回数返却や新規予約を伴わない。

レート制限を有効にした場合の1分あたり上限はauthSession=5（接続元）、authMe=30、status=30、reserve=10、started=20、result=10（認証SID）。DELETEもauthMe枠を使う。通常のControl起動はrate_limit_enabled=false、単独Settingsの既定はtrue。

## 12. 管理機能と設定

管理APIはローカル専用でログイン機能を持たない。更新要求は同一Origin（指定時）、X-JBSL-Admin: 1、application/jsonが必要。cross-site要求を拒否する。JBSL-WEB中継の管理者Cookie/CSRF方式とは異なる。

| Method | Path | 内容 |
|---|---|---|
| GET | /admin/、/guide、/healthz | 管理UI、ガイド、管理側health |
| GET | /admin/api/overview | URL、設定、generation、Viewer設定 |
| PUT | /admin/api/settings | behaviorとgenerationで楽観ロック保存 |
| GET | /admin/api/logs | role、errors、afterで通信履歴取得 |
| POST | /admin/api/logs/clear | 通信履歴クリア |
| GET | /admin/api/probe/{league_id} | 上流projection確認 |
| GET | /admin/api/state | 保存データ概要・要求件数 |
| GET | /admin/api/challenges、/admin/api/challenges/{challenge_id} | Challenge一覧・詳細 |
| GET | /admin/api/results、/admin/api/results/{result_id} | 結果一覧・詳細 |
| GET | /admin/api/budgets、/admin/api/audit | 回数・監査 |
| POST | /admin/api/actions/{action} | clear-cache、expire-sessions、clear-rate-limitsのみ |

一覧はpage既定1、page_size既定25・最大100。Challengeはstatus / league_id / sid / q、結果はranking / end_type / league_id / sid / qで絞り込める。force-endや回数返却の管理APIはこの仮サーバには存在しない。

通常起動はrun.py / start.batでAPIと管理を別ポートで提供する。保存先はdata/control.json、data/score.sqlite3、data/replays/。単独SettingsのDB既定名score_manager.sqlite3と混同しない。ポート・data-dirは起動引数で変更する。

behaviorで上流URL・timeout、stub SID/名前、遅延・障害注入、受付猶予・境界・任意timeout、開始期限profile、cache TTL、サイズ上限、セッション寿命、レート制限、テスト時計差を変更できる。起動と配布の詳細は[README](../server/mock_servers/score_manager/README.md)を参照する。

## 13. 現在の連携上の制約

| 項目 | 実装から確認できる挙動 |
|---|---|
| participants.name | 中継サーバはparticipants各要素へnameを追加するが、本仮サーバのvalidate_projectionはsidだけのobjectを要求する。そのまま接続すると502 upstream_invalidになる。SIDのみの仮サーバ用fixtureと中継応答を同一視しない |
| 対象外status | league_not_foundのcache.fetchedAt=nullを、ViewerのStrictJson.ParseStatusは受理しない。Viewer側では不正応答扱いになり得る |
| UTC表記 | Pythonが許す非UTC offset表記をViewerは拒否する |
| 結果の採否 | metadataと基本BSOR識別の検証範囲。再計算済みスコアとして扱えない |
| 再送期限 | 同一結果でもresult期限を超えた再送は拒否される |

これらは文書改訂で解消されたコード差分ではない。接続時の前提と実装上の不一致として記録している。

## 14. 検証の参照先

既存の[tests](../server/mock_servers/score_manager/tests)には、認証、厳密な要求schema、status、started、結果・BSOR、期限、同時予約、成功応答snapshot、管理操作の試験がある。Viewer側の[HttpContractScenarios.cs](../JBSLViewer.Qualifier.Tests/HttpContractScenarios.cs)と[OutboxScenarios.cs](../JBSLViewer.Qualifier.Tests/OutboxScenarios.cs)も連携確認に用いる。

本改訂の確認対象はソースとの照合、文書内JSON・参照リンク、文書間の規約一致である。既存テストの存在と、今回その全テスト・実機試験を実行したことは区別する。

# JBSL-WEB Qualifier API仕様書

## 0. 文書情報と実装基準

| 項目 | 内容 |
|---|---|
| API版 | Qualifier Version 1 |
| 作成日 | 2026-09-06 |
| 最終改訂 | 2026-09-13 |
| 改訂 | Revision 10。指定された完成版ソースに合わせて実装仕様へ更新 |
| 基準実装 | mock_servers/jbsl_web_proxy |
| 利用クライアント | JBSLViewer、スコア管理サーバ、公開登録画面、管理画面 |
| ステータス | ソースコード照合済み。実JBSL-WEBのDjangoモデル変更完了を示す文書ではない |

本書は現在の中継サーバによるleaderboard拡張、公開Qualifier一覧・SID追加、管理APIを定義する。旧版のLeague/QualifierMapSettingモデル追加案は、現在のcontrol.jsonとfixtureの実装説明へ置き換えた。

関連文書:

- [全体設計](JBSL_Qualifier_Design_For_GPT-5.6Sol.md)
- [仮スコア管理API仕様](JBSL_Qualifier_Score_Manager_API_Specification.md)

主な根拠:

| 内容 | ソース |
|---|---|
| leaderboard中継・fixture結合 | [jbsl_web_proxy_server.py](../server/mock_servers/jbsl_web_proxy/jbsl_web_proxy_server.py) |
| リーグ取込、保存、revision、公開対象判定 | [control.py](../server/mock_servers/jbsl_web_proxy/control.py) |
| 公開API・追加制限 | [public_qualifiers.py](../server/mock_servers/jbsl_web_proxy/public_qualifiers.py) |
| 管理API・Origin制御 | [admin_server.py](../server/mock_servers/jbsl_web_proxy/admin_server.py) |
| 管理認証 | [admin_auth.py](../server/mock_servers/jbsl_web_proxy/admin_auth.py) |
| schema | [schemas.py](../server/mock_servers/jbsl_web_proxy/schemas.py) |
| 名前・曲時間補完 | [scoresaber.py](../server/mock_servers/jbsl_web_proxy/scoresaber.py)、[beatsaver.py](../server/mock_servers/jbsl_web_proxy/beatsaver.py) |
| 公開URL・Host制御 | [config.py](../server/mock_servers/jbsl_web_proxy/config.py) |

## 1. 構成と責務

中継サーバは実JBSL-WEBのランキングを読み取り、保存したQualifier設定を重ねて公開する。回数消費、challenge、score session、結果、BSORはスコア管理サーバが担当する。

| 情報 | 現在の供給元 |
|---|---|
| league_id、league_title、total_rank、maps、既存scores | 実JBSL-WEB、または保存した上流応答 |
| isLive、isOpen、end、qualifier | 中継側fixture。対象リーグの上流値を上書き |
| participants | 手動SID設定 + 任意のランキングSID自動追加 |
| characteristic、difficulty、song_duration_seconds、qualifier_attempt_limit | mapsに対応するfixture |
| participants[].name | total_rankの有効名 → ScoreSaber取得・cache → SID |
| 使用済み回数・残回数 | スコア管理サーバ |

participantsは中継側の参加者集合であり、DjangoのLeague.playerをそのまま取得した証明ではない。公開SID追加は本人認証をしない。Viewer/スコア管理サーバは、別途確認したユーザーSIDとこの集合を照合する。

通常起動はAPIと管理・公開画面を別の待受で提供する。

| 役割 | 既定URL |
|---|---|
| 中継API | http://127.0.0.1:18080 |
| 管理画面 | http://127.0.0.1:18764/admin/ |
| 公開一覧 | http://127.0.0.1:18764/qualifiers/ |
| Swagger | http://127.0.0.1:18080/docs |

## 2. 外部から呼び出すAPI

| Method | Path | 待受 | 認証 |
|---|---|---|---|
| GET | /leaderboard/api/{leagueId} | API | 不要 |
| GET | /healthz、/__mock__/state | API | 不要 |
| GET | /docs、/openapi.json | API | 不要 |
| GET | /qualifiers/ | 管理・公開 | 不要 |
| GET | /public/api/qualifier-leagues | 管理・公開 | 不要 |
| POST | /public/api/qualifier-leagues/{league_id}/participants | 管理・公開 | 不要、Origin等の条件あり |
| GET | /admin/、/guide、/healthz | 管理・公開 | ページ表示・healthは不要 |
| 各種 | /admin/api/* | 管理・公開 | login以外は管理者session |

中継APIの公開GETはleaderboard用である。Viewer用eligibilityや専用server snapshot endpointは設けていない。/api/active_leagueや/api/playlist_songsをそのまま公開中継する汎用ルートも存在しない。

管理機能が実JBSL-WEBへ取得できるパスは、固定origin https://jbsl-web.herokuapp.com の次のGETに限定する。

- /api/active_league
- /api/playlist_songs/{playlistId}
- /leaderboard/api/{leagueId}

任意URLを受け取って転送する方式ではない。ViewerのCookie、ticket、Authorizationは上流へ転送しない。Control経由の上流応答上限は16 MiB、timeoutは20秒、redirect追従なし。

## 3. GET /leaderboard/api/{leagueId}

leagueIdは先頭0のない正の10進整数とする。空文字、不正文字、0、負値、先頭0は400 malformed_request。

### 3.1. 既存情報の保持と拡張

設定済みリーグでは上流JSONを複製し、ルートのisLive、isOpen、end、participants、qualifierをfixture値で置き換える。league_id、league_title、total_rank、mapsの順序、scores、lid、bsrなど既存・未知の項目は保持する。

各mapはfixtureのlidまたはindexで対応付け、次の4項目を設定する。

| field | 型・意味 |
|---|---|
| characteristic | 空でない文字列。例: Standard |
| difficulty | Easy / Normal / Hard / Expert / ExpertPlus |
| song_duration_seconds | 有限の正数またはnull。等速の曲時間、秒 |
| qualifier_attempt_limit | Qualifier有効時はJSON整数1〜100、無効時はnull |

既存hashを譜面識別に使い、songHashや別のmapIdを追加しない。MapKeyはhash + characteristic + difficulty。hashは照合時に空白除去・大文字化し、40桁16進として検証する。中継は元のhash文字列表記まで必ず書き換える実装ではない。

### 3.2. ルートfield

| field | 型・意味 |
|---|---|
| league_id | 正のJSON整数 |
| league_title | 文字列 |
| isLive / isOpen | bool |
| end | offset付き日時文字列。連携ではUTCを使用 |
| participants | SID重複のないobject配列 |
| qualifier | 以下の5項目を持つobject |
| maps | 上流順のmap配列。MapKey重複不可 |

| qualifier field | 型・意味 |
|---|---|
| enabled | bool |
| submission_method | 保存設定ではexternal_leaderboard / jbsl_qualifier_v1 |
| revision | 文字列。管理保存では1〜19桁の正の10進整数文字列 |
| starts_at | UTC日時またはnull。nullは開始下限なし |
| ends_at | UTC日時またはnull。nullはルートendを使用 |

disabled設定ではsubmission_method=external_leaderboard、starts_at/ends_at=null、すべての上限=nullとする。enabled設定は少なくとも1譜面を持ち、開始日時があれば実効終了日時より前であることを保存時に検証する。

enabled=trueでもsubmission_methodがexternal_leaderboardの設定は保存validation上は許される。Viewer・スコア管理サーバはjbsl_qualifier_v1だけをChallenge対象とする。

participantsの保存fixtureはsidのみ。中継出力はsidとnameを持つ。SIDは文字列のまま保持し、大小文字・先頭0を変えない。nameは表示用で認証に使わない。

### 3.3. Response例

以下は保存設定を適用した架空リーグの例である。schemaVersionをleaderboardのルートへ追加する契約ではない。

~~~json
{
  "league_id": 3023,
  "league_title": "Example Qualifier",
  "isLive": true,
  "isOpen": true,
  "end": "2026-09-13T13:00:00.000Z",
  "total_rank": [
    {
      "sid": "76561198000000000",
      "name": "Example Player",
      "standing": 1
    }
  ],
  "participants": [
    {
      "sid": "76561198000000000",
      "name": "Example Player"
    }
  ],
  "qualifier": {
    "enabled": true,
    "submission_method": "jbsl_qualifier_v1",
    "revision": "42",
    "starts_at": "2026-09-13T10:00:00.000Z",
    "ends_at": null
  },
  "maps": [
    {
      "title": "Example Song",
      "lid": "900001",
      "bsr": "example",
      "hash": "0123456789ABCDEF0123456789ABCDEF01234567",
      "scores": [],
      "characteristic": "Standard",
      "difficulty": "ExpertPlus",
      "song_duration_seconds": 120.0,
      "qualifier_attempt_limit": 3
    }
  ]
}
~~~

### 3.4. 未設定リーグと動作モード

通常のControl経由での動作:

| 対象 | upstream_mode=live | upstream_mode=snapshot |
|---|---|---|
| source=liveの保存済みリーグ | 最新leaderboardを取得し設定を結合 | 保存済みupstreamに設定を結合 |
| source=sampleの同梱リーグ | 保存済みサンプルへ設定を結合 | 同左 |
| 中継に未設定のリーグ | 上流GETのJSON本文をそのまま返す | 同じく上流へGETする |

未設定リーグへQualifier fieldを自動合成しない。Qualifier拡張のない応答でも従来のランキングとして返せるが、ViewerのChallenge契約は成立しない。

snapshotはすべての外部通信を停止する設定ではない。未設定リーグの透過GETやScoreSaberの名前補完は残る。直接create_app(Settings)で起動した検証用経路にはoffline_upstream_dirがあり、通常のControlのupstream_modeとは別の設定経路である。

## 4. 保存形式、取込、revision

通常の永続化先はdata/control.json。管理認証は別のdata/admin_auth.sqlite3に保存する。

control.jsonはschemaVersion=1、generation、behavior、leagues、activeを持つ。各leaguesエントリーはfixture、upstream、source、importedAt、notesを持つ。sourceはsampleまたはlive。要求処理中は設定snapshotを参照し、更新はコピー作成・一時ファイル書込み・flush/fsync・os.replaceで反映する。

### 4.1. fixture例

~~~json
{
  "isLive": true,
  "isOpen": true,
  "end": "2026-09-13T13:00:00.000Z",
  "participants": [
    { "sid": "76561198000000000" }
  ],
  "auto_add_ranking_sids": true,
  "qualifier": {
    "enabled": true,
    "submission_method": "jbsl_qualifier_v1",
    "revision": "42",
    "starts_at": "2026-09-13T10:00:00.000Z",
    "ends_at": null
  },
  "maps": [
    {
      "lid": "900001",
      "characteristic": "Standard",
      "difficulty": "ExpertPlus",
      "song_duration_seconds": 120.0,
      "qualifier_attempt_limit": 3
    }
  ]
}
~~~

map selectorはlidまたは0始まりindexの片方だけ。上流の各mapにちょうど1つ対応させる。欠落、曖昧なlid、重複対応、余分なselectorは409 mock_fixture_invalidになる。hashだけで難易度やcharacteristicを推測しない。

### 4.2. 実リーグの取込

1. 管理画面でactive_leagueを取得する。JSON配列、ID重複、状態・日時を検証し、isLive/isOpenがともにtrueの項目を保存する。
2. 選択したIDのleaderboardと、playlist_idが正の整数ならplaylist_songsを取得する。
3. mapとplaylist songはlidと正規化hashの両方で照合し、一意な場合だけchar/diff等を補完する。
4. 各mapに一意のlidがあればlid、そうでなければindexを付ける。不足する難易度・characteristicは空のまま管理者へ確認表示する。
5. 取込draftはメモリ内に保持する。初期値はQualifier無効、上限null、手動participants空、ランキングSID自動追加true。
6. 管理者が確認して保存した時点で永続化する。

既存設定の再読込・保存では既存のupstreamとfixtureが基準となる。現在のlive leaderboardへの中継時に構成が変わっていれば、保存済みselectorとの不一致を検出する。

### 4.3. revisionの実際の更新規則

- 管理保存はexpectedRevisionと現在値の一致を確認する。未保存draftはnullを指定する。
- 保存に成功すると現在値+1、新規保存は"1"。送信fixture内のrevisionはサーバ計算値で上書きする。
- 同じ設定内容を保存してもrevisionは増える。
- previewは次のrevisionを含む結合結果を返すが、永続化しない。
- 公開SID追加で新規手動参加者を保存した場合も+1。既登録SIDの再送では増えない。
- ランキングSIDの動的追加、名前・曲時間の応答時補完、上流ランキングの変化だけでは保存revisionを増やさない。
- behaviorの楽観ロックは別の整数generationを使う。

したがってrevisionは保存設定の編集世代であり、応答JSON全体のハッシュや全変化の検知値ではない。スコア管理サーバの新規予約はrevisionが同じでも上流を再取得する。

## 5. SIDと名前・曲時間の補完

### 5.1. ランキングSID自動追加

auto_add_ranking_sidsの省略時既定はtrue。手動participantsを先に置き、total_rank、続いて各map.scoresにある空白を含まない文字列SIDを重複なく追加する。ランキングだけに存在するSIDも対象になる。

手動設定からSIDを削除しても、自動追加が有効でランキングに残っていれば中継応答には再び含まれる。自動追加で応答に載っただけのSIDを公開APIで登録すると、手動参加者として新規保存されるためadded=trueになり得る。

### 5.2. 名前

有効なtotal_rank[].nameを優先する。存在しないSIDはScoreSaberの固定GET /api/v2/players/{sid}を用いて補完する。数字のみのSIDだけが問い合わせ対象で、応答idの完全一致を確認する。独自文字列SIDは変更せず、その値を表示名として使う。

成功cacheは1時間、失敗時の再問い合わせ抑制は60秒、最大4096件、同時取得は最大4件。1応答の補完待ちは既定3秒。取得に失敗した場合は既存cacheまたはSIDを使い、Qualifier参加資格の取得自体を失敗させない。上流total_rankやscoresの名前を書き換えず、participantsの結合コピーだけを補完する。

### 5.3. 曲時間

BeatSaverの固定originへGET /maps/hash/{hash}し、metadata.durationの正の有限値を利用する。取得はhash単位でまとめ、同時最大4件。取込・編集画面用コピーを補完し、live中継では欠損した曲時間だけを補完する。失敗時は既存値またはnullを維持する。

Viewerの開始期限判定に使うのはインストール済み譜面のローカルsongDurationである。中継の曲時間は表示・サーバ側の任意開始期限profileで用いられる。

## 6. 公開Qualifier一覧とSID追加

### 6.1. GET /public/api/qualifier-leagues

ログイン不要。/qualifiers/の画面が呼び出す。

~~~json
{
  "items": [
    {
      "id": 3023,
      "name": "Example Qualifier",
      "startsAt": "2026-09-13T10:00:00.000Z",
      "endsAt": "2026-09-13T13:00:00.000Z"
    }
  ],
  "fetchedAt": "2026-09-13T09:00:00.000Z",
  "serverTime": "2026-09-13T09:00:10.000Z",
  "source": "live",
  "stale": false,
  "canAddSid": true
}
~~~

掲載条件は、保存したactive一覧にあり、保存リーグのsource=live、activeとfixtureのisLive/isOpenがともにtrue、双方のleague.endが現在より後、qualifier.enabled=trueであること。同梱sample、未取込、未保存、無効、停止、リーグ終了済みは掲載しない。

公開一覧はChallenge開始可否判定ではない。starts_atによる下限、submission_method、qualifier.ends_atによる受付判定はこの一覧の選別条件に含まれない。Qualifier開始前のSID登録が可能であり、表示中でもViewerのChallenge条件を満たすとは限らない。

liveではactive取得後60秒未満の成功cacheを再利用し、同時取得をまとめる。失敗すると前回一覧をstale=trueで表示し、SID追加を止める。失敗後は60秒間再取得を抑制する。snapshotでは保存済みactiveを使い、stale=false、取得日時があればcanAddSid=trueとする。

### 6.2. POST /public/api/qualifier-leagues/{league_id}/participants

~~~http
POST /public/api/qualifier-leagues/3023/participants
Content-Type: application/json
Origin: https://relay.example.com
X-JBSL-Public: 1
~~~

~~~json
{
  "sid": "76561198000000000"
}
~~~

Originは実際に画面を提供している同一originへ置き換える。必須条件は同一Origin、X-JBSL-Public: 1、application/json、Sec-Fetch-Siteがcross-siteでないこと。管理者Cookie・CSRFは不要。bodyは1 KiB以下でsid以外のキーを拒否する。

SIDは前後空白を除去後、1〜128文字、表示可能文字のみ、内部空白・改行・制御文字なし。大小文字・先頭0を保持する。本人確認やScoreSaberアカウントの存在確認を登録条件にしない。

~~~json
{
  "leagueId": 3023,
  "added": true,
  "revision": "43"
}
~~~

新規登録と登録済み再送はいずれも200。既存の手動参加者ならadded=false、revisionは不変。要求時に最新の公開対象とactive freshnessを再確認し、同じ保存ロック内で重複確認・追加・revision更新を行う。

同一接続元の追加要求は60秒間に10回まで。コード上の集計キーはrequest.client.hostである。公開APIには削除、置換、設定更新のルートはない。

| HTTP | code | 条件 |
|---|---|---|
| 400 | invalid_json / invalid_participant_fields | JSON objectでない、sid以外のキー |
| 403 | cross_origin / origin_required / public_header_required | Origin・ヘッダー条件不成立 |
| 404 | qualifier_not_available | 現在の公開対象でない |
| 409 | qualifier_settings_invalid | 保存設定を検証できない |
| 413 | body_too_large | 1 KiB超過 |
| 415 | json_required | Content-Type不正 |
| 422 | invalid_sid | SID形式不正 |
| 429 | rate_limited | 追加回数制限 |
| 503 | active_leagues_unavailable / participant_save_failed | 開催状況確認・永続化失敗 |

## 7. 管理認証

/admin/のHTMLは匿名で取得できるが、/admin/api/login以外の管理APIはsession認証を必須とする。

| Method | Path | 入出力 |
|---|---|---|
| POST | /admin/api/login | username、passwordを持つJSON。成功はusername、csrfToken、expiresAt |
| GET | /admin/api/me | 同じsession情報を返す |
| POST | /admin/api/logout | sessionを失効しCookieを削除、204 |

Cookie名はjbsl_relay_admin、Path=/admin、HttpOnly、SameSite=Strict。HTTPSではSecureを付け、Max-Ageは8時間。DBでsessionを保存し、再起動後も期限内なら利用できる。同じユーザーのsessionは最新5件まで。Cookie値はSHA-256化して保存する。

管理更新はX-JBSL-Admin: 1、application/json、cross-siteではないことが必要。Origin指定時は同一originを要求する。login以外の更新ではさらにCookieとX-CSRF-Tokenを検証する。login自体にはCSRFは不要である。

管理者はローカルコンソールのstart.bat initまたはstart.bat set-admin <username>で設定する。Webから初期管理者を作成しない。パスワードは12〜256文字、scryptでsalt付き保存。再設定は当該ユーザーのsessionをすべて失効させる。ログインは接続元ごとに1分5回まで。

代表的な認証エラーは401 invalid_login / admin_login_required、403 csrf_rejected、429 rate_limited。

## 8. 管理API

以下は管理認証後に呼び出す。

| Method | Path | 処理・主要項目 |
|---|---|---|
| GET | /admin/api/overview | URLs、publicMode、behavior、generation、serverTime、viewerConfig |
| GET | /admin/api/leagues | active取得結果とregistered一覧 |
| POST | /admin/api/leagues/refresh | 実JBSLのactive一覧を更新 |
| POST | /admin/api/leagues/{league_id}/import | 取込draftを作成。entry、expectedRevision=null、rankingSids |
| GET | /admin/api/leagues/{league_id} | 編集用entry、expectedRevision、rankingSids |
| PUT | /admin/api/leagues/{league_id} | fixture、expectedRevisionを受け、entryとmergedを返す |
| POST | /admin/api/leagues/{league_id}/preview | 同じ要求で保存前のentryとmergedを返す |
| PUT | /admin/api/settings | behavior、generationを受ける |
| GET | /admin/api/logs | role、errors、afterで絞り込んだitemsとcapacity |
| POST | /admin/api/logs/clear | 通信履歴をクリア |
| GET | /admin/api/probe/{league_id} | ローカル中継APIを呼び、statusとbodyを返す |
| GET | /admin/api/state | proxy要求件数とregisteredLeagues |

一般管理JSONの上限は1 MiB、loginは4096 bytes。設定保存の世代不一致は409 edit_conflict。未取込・不正fixture等は409または422の業務エラーを返す。手動参加者の削除・置換は認証済み管理者によるfixture保存で行う。

behaviorの完全な既定値:

~~~json
{
  "upstream_mode": "live",
  "proxy_fault": "none",
  "proxy_delay_ms": 0,
  "participant_helper_sid": "76561198000000000"
}
~~~

proxy_faultはnone / upstream_unavailable / upstream_invalid / rate_limited / not_found。proxy_delay_msは0〜60000。participant_helper_sidは空白のない1〜128文字の文字列。schemaは厳密型・未知キー拒否。上流originを任意に変更するbehavior項目はない。

## 9. エラー・診断・公開URL

### 9.1. 共通エラー

~~~json
{
  "error": {
    "code": "mock_fixture_invalid",
    "message": "Every upstream map must have one fixture mapping.",
    "retryable": false,
    "requestId": "a9fa7bc6-8221-4c49-9af7-f9c6ef63393a",
    "details": { "leagueId": 3023 }
  }
}
~~~

共通ヘッダーはCache-Control: no-store、X-JBSL-Mock-Server: true、X-Request-ID。管理・公開側ではCSP、nosniff、frame拒否等も付ける。通信履歴は最大1500件のメモリ内リングで、要求body、Cookie、ticket、passwordを記録しない。

通常Control経路の上流404は404 league_not_found、その他の非200・通信失敗は503 upstream_unavailable、不正JSONや上限超過は502 upstream_invalid。fixtureと上流の結合不整合は409 mock_fixture_invalid。障害注入では意図的にHTTP 200の不正JSONを返す場合もある。

### 9.2. 公開URL

アプリ直下config.jsonのpublic_urlを使う。data/control.jsonや--data-dirとは独立した起動設定である。

~~~json
{
  "public_url": "https://relay.example.com"
}
~~~

空文字・未設定・ファイルなしはローカルモード。HTTPSドメインoriginだけを許し、認証情報、パス、query、fragment、独自ポートは拒否する。末尾/と:443は正規化する。

待受はloopbackのまま、設定済み公開Hostを追加で許可する。公開Hostでは内部scopeをHTTPSに揃え、URL・redirect・Cookieを生成する。任意Hostや任意の転送ヘッダーから公開URLを構築しない。公開モードでは管理応答の内部URL・dataDirectoryを公開向け表示へ調整する。

同一ドメインへTunnelで公開する場合は、leaderboard/api、docs、docs-assets、openapi.json、__mock__/stateをAPI側へ、公開画面・public/api・admin等を管理側へ振り分ける。config.jsonだけでDNSやTunnelを作成する機能はない。実際のルーティング例は[README](../server/mock_servers/jbsl_web_proxy/README.md)を参照する。

## 10. Viewer・仮スコア管理との連携

Viewerは既存のLeaderboardモデルを通常画面と専用JBSL CHALLENGE画面で共有する。リーグ一覧はactiveLeagueApiUrlから取得し、選択リーグのleaderboardApiUrlへ本中継を指定する。公開Web一覧APIをViewerのリーグ一覧として使用しているわけではない。

ローカルgateは提出方式、freshな契約、開催状態、SID参加、MapKey、ローカル曲時間、開始期限を確認する。score statusのcacheはこれとは別で、仮スコア管理側の既定はfresh 60秒、障害時参考表示300秒。新規予約は毎回leaderboardを取得する。

実装間の制約:

| 項目 | 現状 |
|---|---|
| participants.name | 本中継はnameを追加する。指定のmock_servers/score_manager/schemas.pyはsidだけを受理するため、そのままの接続ではupstream_invalidになる |
| Viewerのname対応 | StrictJson.ParseLeaderboardはsidを検証し、追加nameを無視するため受理する |
| 時刻 | Pythonのfixture検証は非UTC offsetも受理し、結合時に元文字列を保持する。Viewer用にはZまたは+00:00表記で保存する |
| map title | Viewerはtitleを文字列として必須検証する。中継projectionの検証だけではその条件をすべて保証しない |
| revision | 動的なランキングSID・名前補完では増えない。認可の証明に使わない |
| statusのnull | 仮スコア管理のleague_not_found応答のcache.fetchedAt=nullはViewerが拒否する。詳細はスコア管理API仕様参照 |

本改訂はこのようなコード上の不一致を隠して接続済みとするものではなく、現在の実装と制約を記録したものである。

## 11. 検証と運用の参照

[tests](../server/mock_servers/jbsl_web_proxy/tests)には中継・fixture、ScoreSaber補完、管理編集・認証、公開SID追加、公開URL、画面、runner lifecycleの既存試験がある。起動・管理者初期化・配布ZIP・systemdについては[README](../server/mock_servers/jbsl_web_proxy/README.md)と[run.py](../server/mock_servers/jbsl_web_proxy/run.py)を基準とする。

今回の文書改訂で実JBSL-WEB、ScoreSaber、BeatSaver、Tunnel、ゲーム実機を再試験したとは扱わない。接続先を変更しても、上流・fixture・クライアントそれぞれのschemaを確認する必要がある。

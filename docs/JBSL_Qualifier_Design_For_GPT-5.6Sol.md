# JBSL Qualifier スコア送信機能 設計仕様書

## 0. 文書情報と対象

| 項目 | 内容 |
|---|---|
| 作成日 | 2026-09-06 |
| 最終改訂 | 2026-09-13 |
| 改訂 | Revision 10。指定された完成版ソースとAPI仕様を照合して更新 |
| 対象Viewer | JBSLViewer/JBSLViewer、JBSLViewer/JBSLViewer.Qualifier.Core |
| 対象サーバ | mock_servers/score_manager、mock_servers/jbsl_web_proxy |
| manifest | JBSLViewer 0.4.0、gameVersion 1.39.1 |
| ステータス | 実装仕様。実機・公開環境の動作確認結果とは別 |
| 目的 | 現行コードの構成、通信、状態管理、UI、制約を保守担当者へ引き継ぐ |

本書は元の実装前設計を、指定フォルダの実装に合わせて改訂したものである。古いBeat Saber 1.29.1固定の差し込み先、未実装予定、Djangoモデル追加案を、そのまま完成版の挙動として扱わない。別バージョンのViewerや、JBSLViewer/server内のコピー・別実装score_serverへ自動的に適用する文書ではない。

APIの詳細は同じRevision 10の次の2文書を参照する。

- [JBSL Qualifier スコア管理サーバ API仕様書](JBSL_Qualifier_Score_Manager_API_Specification.md)
- [JBSL-WEB Qualifier API仕様書](JBSL_WEB_Qualifier_API_Specification.md)

JBSLViewer_Qualifier_Client_API_Specification.mdは今回の改訂対象外である。旧資料と異なる箇所は、指定ソースと今回の3文書を基準に確認する。

## 1. 現行構成の要点

1. メインメニューのJBSL CHALLENGEと、既存ランキングパネルのCHALLENGEから専用画面へ入る。
2. 専用画面はリーグ一覧、対象曲一覧、譜面詳細、ゲーム設定、ランキング、提出状態を組み合わせる。
3. 専用画面のPRACTICEはJBSL challengeを予約しない通常のSolo再生。CHALLENGEは確認後の予約成功を待って開始する。
4. 新規挑戦の資格は、Viewerのローカルgate、score status、予約時のサーバ検証の各段階で確認する。
5. 認証はplatform ticketから作るCookie session。認証応答SIDと現在のplatformUserIdが一致しなければ先へ進めない。
6. 回数は予約成功時にユーザー・リーグ・MapKeyごとに1回消費する。結果保存の成功とは独立している。
7. 予約の応答が不明な場合は同じキーとbodyで回復する。遅れて成功が分かっても自動Playしない。
8. 実GameplayでMapKey・Solo・提出可否を再確認し、元challengeの世代だけを録画・集計する。
9. clear、fail、中断、Restart、開始失敗、想定外終了を結果へ変換する。再開された別Gameplayへ元challengeを引き継がない。
10. 結果は送信前にOutboxへ永続保存する。保存した所有者・送信先・同じ結果IDで再送する。
11. 中継サーバは保存したQualifier設定、公開SID追加、ランキングSIDと名前の補完を提供する。
12. 指定の仮スコアサーバは基本BSOR識別検証までで、スコア再計算・公開ランキング集計は行わない。

## 2. ソース構成と寿命

| 層 | 主な実装 | 役割・寿命 |
|---|---|---|
| 契約・判定 | Contracts、QualifierEligibilityEvaluator、GateToken | ゲーム依存を分離した共通C# |
| 予約・完了制御 | QualifierChallengeCoordinator、ChallengeContext、ReserveOperation | メニュー・Gameplayをまたぐ |
| 認証・HTTP | AuthenticationSession、ScoreManagerApiClient、ScoreServerEndpoint | 接続先・SID・認証世代ごとのsession |
| 結果保持 | ResultSnapshot、SubmissionHistory、CompletedChallengeGuard、Outbox/* | 終了snapshot、重複終了防止、永続再送 |
| App scope | QualifierRuntime、QualifierDispatcher、PlayerIdentityService、SubmissionEligibilityTracker、QualifierRoomState | 起動から終了まで |
| 共通ランキング | Leaderboard、LatestUpdate、ActiveLeague等 | 通常表示と専用画面で共用 |
| Menu scope | QualifierMenuController、StandardPlayAdapter、QualifierDirectPlayController、UI/*、QualifierRestartUiController | 選択・起動・結果画面 |
| Player scope | QualifierGameplayObserver、QualifierReplayRecorder | 1Gameplayの監視・録画 |
| Python仮スコア | score_manager_server、database、bsor_reader等 | Cookie、回数、結果・BSOR保存 |
| Python中継 | jbsl_web_proxy_server、control、public_qualifiers、admin_auth等 | 上流JSON拡張・参加者設定 |

根拠は[JBSLViewerAppInstaller.cs](../JBSLViewer/Installers/JBSLViewerAppInstaller.cs)、[JBSLViewerMenuInstaller.cs](../JBSLViewer/Installers/JBSLViewerMenuInstaller.cs)、[JBSLViewerPlayerInstaller.cs](../JBSLViewer/Installers/JBSLViewerPlayerInstaller.cs)。

Unityオブジェクト、platform user、画面操作はメインスレッドで扱う。HTTP、BSOR encode/gzip、Outboxファイル保存などは非同期・背景処理へ分け、非同期処理前に元世代の値を確定する。

## 3. 識別子と共有契約

| 識別子 | 意味 |
|---|---|
| leagueId / league_id | 正の整数。score APIとleaderboardでfield名が異なる |
| SID | IPlatformUserModel.GetUserInfo()のplatformUserId。文字列で完全一致 |
| MapKey | hash + characteristic + difficulty |
| qualifier.revision | 中継の保存設定の編集世代。認可証明ではない |
| challengeId | サーバが予約成功時に発行するUUID |
| reserve key | 1つの予約操作に固定したIdempotency-Key |
| clientResultId | 結果作成に使用するUUID。resultのIdempotency-Keyと一致 |
| submissionId | サーバに保存された結果のUUID |
| SelectionGeneration | 選択情報を変更した世代 |
| AuthenticationGeneration | SID・接続先等による認証構成の世代 |
| GameplayGeneration | 実Gameplayインスタンスの世代 |

hashは40桁16進を大文字へ正規化する。Expert+ / Expert PlusはExpertPlusに揃える。characteristic、SIDは大小文字を含め完全一致し、SIDを整数にしない。異なる難易度をhashだけで同一視しない。

ViewerはStrictJsonで重複JSONキー、コメント、非有限数、重要項目の型、MapKey・SID重複を拒否する。JSON全体の未知キーを一律拒否する方式ではない。participants[].nameなどの追加表示情報は読み捨てられる。

時刻はUTCのZまたは+00:00表記を使う。Python入力の許容表記の方が広いため、offset付きなら常にViewerと互換とは限らない。

## 4. 通信フロー

~~~mermaid
sequenceDiagram
    participant V as JBSLViewer
    participant R as JBSL-WEB中継
    participant S as 仮スコア管理
    V->>R: GET /leaderboard/api/{leagueId}
    R-->>V: ランキング・Qualifier設定・participants
    Note over V: ローカルgateを確認
    V->>S: POST /api/v1/auth/session（必要時）
    S-->>V: Cookie・認証SID・期限
    Note over V: 認証SIDと現在SIDを照合
    V->>S: GET /api/v1/qualifiers/status
    S->>R: cache未取得・期限超過ならGET
    S-->>V: 資格・上限・残回数
    Note over V: CHALLENGE → CONFIRM
    V->>S: status再確認
    V->>S: POST /api/v1/qualifiers/challenges
    S->>R: 新規予約は毎回GET
    S->>S: 回数・challenge・応答snapshotをcommit
    S-->>V: challengeId・受付期限・残回数
    Note over V: 世代・資格を再確認して1回だけ起動
    V->>S: POST .../{challengeId}/started
    Note over V: 実Gameplay終了 → 元contextを切り離す
    Note over V: metadata・BSORを確定 → Outboxへ保存
    V->>S: PUT .../{challengeId}/result
    S-->>V: 保存結果
~~~

これはAPIの意図された呼出し順である。指定中継と仮スコアのparticipants.name不一致は第16節に記載しており、この図自体は現行3コンポーネントの接続試験成功を示さない。

通常PLAYや専用PRACTICEはこの予約・結果フローに入らない。対象外の選択中でも、既存予約や保存済み結果の回復通信は所有者・接続先が一致する場合に行う。

## 5. リーグ取得とcache

[Leaderboard.cs](../JBSLViewer/Models/Leaderboard.cs)のリーグ別ConcurrentDictionaryを通常ランキングと専用Qualifier画面で共有する。GetLeaderboardAsyncはリーグごとに進行中Taskを共有し、重複要求を抑制する。reload=trueでも進行中の同じリーグ取得は共有する。

fresh条件は次のすべて:

- そのリーグの取得失敗が記録されていない。
- そのリーグの取得が進行中でない。
- cacheが存在する。
- jbslViewerGetTimeがLatestUpdate._latest以上。

既定のrefreshIntervalは10分で、LatestUpdateが見出し情報と時間経過を基に更新境界を進める。単純な「Qualifier専用の固定60秒TTL」ではない。score statusの10秒cacheやサーバ側60秒cacheとは別である。

元JSONをqualifierSourceJsonとして保持し、StrictJson.ParseLeaderboardの成功結果をqualifierContractに置く。不正なQualifier情報はqualifierValidationErrorに記録する。既存ランキング表示用オブジェクトは保持できても、Challengeを許可する契約としては使えない。

同一リーグ内で譜面・難易度を選ぶだけでは中継へ追加GETしない。専用画面のリーグ選択、RELOAD、プレイからの復帰などでは必要に応じて再取得する。

## 6. 画面構成

### 6.1. 専用画面への入口

[QualifierMenuEntry.cs](../JBSLViewer/Qualifier/UI/QualifierMenuEntry.cs)がメインメニューへJBSL CHALLENGEを登録する。既存LeaderboardPanelのCHALLENGEも、現在のリーグ・MapKeyを渡して専用画面を開く。

この入口ボタンは「現在曲の資格が成立したときだけ表示する旧設計」とは異なる。LeaderboardPanelは入口領域を表示し、CanOpenで操作可否を判断する。CanOpenはMainまたはSoloの画面で、専用画面未表示、遷移中でない、選択ロック・起動待ちがないことなどを確認する。

### 6.2. リーグ・曲・詳細

[QualifierFlowCoordinator.cs](../JBSLViewer/Qualifier/UI/QualifierFlowCoordinator.cs)は次の画面を管理する。

| 画面 | 挙動 |
|---|---|
| リーグ一覧 | ActiveLeagueの既存一覧を表示。RELOADで再取得 |
| リーグ選択 | leaderboardのfreshness、方式、取得時SIDと現在SID、参加者、対象曲を確認 |
| 非参加・不正リーグ | 理由を通知しリーグ一覧へ戻す |
| 曲一覧 | 契約にあるMapKey単位。インストール済みcustom_levelの対応を検索 |
| 未導入曲 | Install it, then RELOADと表示。自動ダウンロード処理はない |
| 曲詳細 | 対象難易度を読み込み、曲時間・BPM・NPS・NJS・ノーツ数等とPRACTICE / CHALLENGEを表示 |
| 設定・ランキング | ゲームのGameplaySetupと既存ランキング表示を利用 |
| 提出状態 | 残回数、理由、予約・再送・未解決状態を表示 |
| 結果 | 専用に複製した標準ResultsViewControllerを利用 |

リーグ入場確認と、実際のChallenge開始gateは分かれている。入場できても期間外・回数不足等でCHALLENGEを開始できない場合がある。

曲読込みはBeatmapKey、BeatmapLevelData、BasicBeatmapDataを確認する。リーグ・曲を切り替えた非同期処理はroom generationとCancellationTokenで破棄する。ランキングの対象行もMapKey全体で対応付け、曖昧な重複を選ばない。

### 6.3. PRACTICEの意味

専用画面のPRACTICEはchallenge contextなしで通常のStartStandardLevelを呼ぶ。practiceSettingsはnullなので、Beat Saber標準の時間指定Practiceモードと同じ意味ではない。

このPRACTICEや通常PLAYはJBSL予選の回数を消費せず、Qualifier用録画・result送信を行わない。他のModの通常スコア送信まで無効化する処理ではない。

## 7. 新規Challengeのローカルgate

[QualifierEligibilityEvaluator.cs](../JBSLViewer.Qualifier.Core/QualifierEligibilityEvaluator.cs)は以下を確認する。

- Soloとして有効な選択で、Scene遷移中・Replay再生中ではない。
- freshなleaderboard契約があり、leagueIdが一致する。
- qualifier.enabled=true、submission_method=jbsl_qualifier_v1、revisionが空でない。
- isLive=true、isOpen=true。
- 現在SIDが空でなく、participantsにちょうど1回存在する。
- SIDとMapKeyに重複がなく、選択MapKeyがちょうど1件存在する。
- その譜面の上限が1〜100。
- ローカルsongDurationが正の有限値である。
- starts_at以前でなく、現在時刻がeffectiveEnd - ローカルsongDuration以下である。

effectiveEndはqualifier.ends_at、nullならleague.end。曲時間をsongSpeedMultiplierで割ったり、Pause予定時間を足したりしない。

ローカルgateが成立して初めて新規挑戦用の認証・statusへ進む。CoreのCanChallengeはさらに、現在の認証sessionに属する10秒未満のstatus、eligible=true、reasonCode=eligible、残数>0、cache.stale=false、提出可能、未解決処理なしを要求する。

ローカルgateは不要通信の抑制であり、サーバ認可を代替しない。専用画面への入口表示条件とも同一ではない。

## 8. 認証・接続先・非同期世代

[PlayerIdentityService.cs](../JBSLViewer/Qualifier/PlayerIdentityService.cs)はplatform userを読み、5秒間隔で再確認する。SteamではGetAuthenticationToken、OculusではGetXPlatformAccessTokenを使用してticketを得る。

[AuthenticationSession.cs](../JBSLViewer.Qualifier.Core/AuthenticationSession.cs)は同時認証を1本のTaskへまとめる。既存Cookieがあればauth/me、必要ならticketでauth/sessionを呼ぶ。authenticated=true、user.sid=現在SID、expiresAtが未来であることを確認する。失敗した自動認証を毎tick無限に繰り返さず、明示再試行待ちにする。

ScoreSessionはCookieContainer、HttpClient、所有者SID、接続先、generationを持つ。HttpClientHandlerはredirect追従・proxy利用を無効にする。ticket文字列は認証後に参照をクリアする。Cookieとticketを永続Outboxやログへ書かない。

ScoreServerEndpointはHTTPSを許可し、HTTPはallowDevelopmentHttp=trueかつ127.0.0.1 / localhostのみ。userinfo、query、fragmentは拒否する。接続先identityは小文字scheme/host、実効port、末尾/を持つbase pathで正規化する。異なるpathやportは別サーバとして扱う。

GateTokenは選択世代、認証世代、正規化接続先、leagueId、MapKey、SID、revision、Solo状態を束ねる。古いstatusが到着しても現在gateが異なれば採用しない。同じSIDの再認証でもCookieContainerが置き換わるため、statusを得たScoreSession自体が現在の認証sessionであることも確認する。

## 9. CHALLENGE確認と予約

[QualifierChallengeCoordinator.cs](../JBSLViewer.Qualifier.Core/QualifierChallengeCoordinator.cs)が確認・予約を制御する。

1. CHALLENGEで確認画面を開き、選択gateを保存して曲・難易度・設定をロックする。
2. CONFIRMで現在gate、提出状態、Outbox空き容量を再確認する。
3. 認証とstatusを再確認し、残回数・stale・未解決状態を検証する。
4. UUIDキー、固定body、所有者、接続先、確認時刻を持つReserveOperationを作る。
5. サーバの予約成功を待ち、返ったMapKey・現在のSID/世代/接続先・ローカル資格・提出状態を再確認する。
6. 条件が継続している場合だけActiveChallengeを設定し、Playを1回呼ぶ。

サーバ側はBEGIN IMMEDIATE内で最新leaderboard取得、回数チェック・加算、challenge作成、成功応答snapshot保存を行う。成功済み同一キーは上流再取得・追加消費なしで同じsnapshotを返す。

### 9.1. timeoutと遅延成功

UI待ち時間は既定30秒。HTTPのreserve処理はUI待ち時間を超えて遅延成功を観測できるよう、通常要求timeoutの3倍（下限1秒）まで維持する。

UI timeout後は通常画面のロックを解除し、PendingReserveを残す。再送は元のキー・bodyのまま指数backoffし、最大60秒間隔へ進む。新しい回復要求には元の所有者SIDと接続先の一致が必要。

timeout後の成功や、SID・接続先・選択が変わった後の成功ではPlayしない。予約されたchallengeをpreflight_rejectedとして確定し、Outboxへ保存する。消費済み回数は戻らない。

PendingReserveはプロセス内の保持で、再起動をまたぐ永続予約journalではない。Outboxへ保存される前にプロセスが終了した予約について、自動回復を保証する照会APIは実装されていない。

## 10. ゲーム起動の2経路

[StandardPlayAdapter.cs](../JBSLViewer/Qualifier/StandardPlayAdapter.cs)はPlay前にSubmissionHistoryを追跡へ接続し、起動元に応じて処理を分ける。

| 起動元 | 実装 |
|---|---|
| 専用Qualifier画面 | QualifierDirectPlayControllerがMenuTransitionsHelper.StartStandardLevelを直接呼ぶ |
| 通常Soloの標準経路 | SinglePlayerLevelSelectionFlowCoordinator.ActionButtonWasPressedをreflectionで呼ぶ |

専用画面は読み込んだBeatmapKey/Level/Data、現在のmodifier・環境・色・player settingsを渡し、gameMode=Solo、practiceSettings=nullで開始する。Solo画面の選択状態を書き換えてから再表示する経路ではない。

DirectPlayはroomのlaunch IDとgenerationを保持し、await後にも一致を確認する。遷移開始前はキャンセルでき、別操作の遅延処理で起動・拒否を行わない。

標準経路はNoFailCheckが介入する手前のprivateボタン転送処理を直接呼ばず、ActionButtonWasPressedを呼ぶ。特定Modのインストール状態を含む実際の互換性はゲーム版ごとの実機試験が必要である。

起動完了はGameplayObserverからの到達通知で確認する。時間経過だけで「開始失敗」と扱わず、明示的な読込みエラー・キャンセル・起動例外・開始未到達の復帰を処理する。通常のメニューScene unloadを失敗扱いにしない。

## 11. 提出可否・Replay・Restart

### 11.1. 提出可否の追跡

[SubmissionEligibilityTracker.cs](../JBSLViewer/Qualifier/SubmissionEligibilityTracker.cs)はBS UtilsのDisabled / ProlongedDisabled、現在のSiraUtil Submission ticketsを読む。状態取得失敗も提出不可として扱う。前回プレイの表示snapshotであるSubmissionDataContainer.Disabledを次回予約の判定に使わない。

SubmissionHistoryは当該プレイで一度でも禁止を観測したことを保持する。allowedAtStartとremainedAllowedを別々に記録し、後から許可へ戻っても過去の禁止を消さない。元プレイから切り離した後は、次のGameplayの通知で書き換えない。

終了時のSiraLevelCompletionResults.ShouldSubmitScoresも元プレイの採否へ反映する。特定のKosorenTool設定名を判定する方式ではない。

JBSL独自のmodifier、NoFail、速度、Pause制限を追加する構成ではない。ただし標準提出禁止状態、Solo/Practice/Replay、MapKeyの不一致は拒否理由になる。

### 11.2. Gameplay開始時の再検証

[QualifierGameplayObserver.cs](../JBSLViewer/Qualifier/QualifierGameplayObserver.cs)はgameMode=Solo、practiceSettings=null、Replayでない、実MapKey=予約MapKey、提出可能を確認する。

失敗はpreflight_rejectedとして元challengeを終了し、採点を抑止してPauseし、Scene遷移が終わってからメニューへ戻す。採点開始直前にも提出可否を確認する。

started APIは開始後の補助通知であり、失敗しても実Gameplayや結果を破棄しない。通知なしでreservedからresult提出できる。

### 11.3. Replay判定

[ReplayModeDetector.cs](../JBSLViewer/Qualifier/Replay/ReplayModeDetector.cs)はBeatLeaderのIsStartedAsReplay、ScoreSaberのReplayState.IsPlaybackEnabledを読む。ScoreSaberのstatic/instance双方のReplayStateを扱い、instanceの場合はPlugin.Instanceから取得する。

対象Modが導入されていてAPIを読めなければ、replay_state_unavailable等として新規Challengeを止める。別Modの実処理を呼んで状態を推測しない。取得失敗コードと実Replay再生を区別する。

### 11.4. Restart

Challenge中のPause・結果画面ではRestartを非表示または操作不能にする。専用画面のPRACTICE結果ではRestartを許す。

迂回Restartを検出すると、元challengeの結果をrestart / restartedとして1回確定し、再プレイはchallenge contextのない通常プレイへ移す。旧GameplayのDispose後に新世代が到着した場合も、元contextを新Recorderへ結び付けない。

CompletedChallengeGuardはchallengeIdとGameplayGenerationの組で終了重複を防ぐ。通常Finish、Dispose、メニュー復帰、次Gameplay開始、終了イベントが競合しても、元結果だけを確定する。想定外にメニューへ戻った場合はunknownとして扱う。

## 12. BSORと結果確定

[QualifierReplayRecorder.cs](../JBSLViewer/Qualifier/QualifierReplayRecorder.cs)が元GameplayのInfo、Frames、Notes、Walls、Heights、Pausesを記録し、[Replay.cs](../JBSLViewer.Qualifier.Core/Replay/Replay.cs)のEncoderがBSOR Version 1を生成する。

終了時にはイベント購読を外し、録画オブジェクトの所有権を切り離す。BSOR info.scoreにはmultipliedScore、modifierには終了時energyを踏まえたコード、Fail時のfailTimeには結果のendSongTimeを設定する。別MapKeyの録画は予約譜面の結果へ添付しない。

結果の確定順序:

1. 元Gameplayの採否履歴・時刻・最終値を取得する。
2. DetachForFinalizationでActiveChallengeから切り離し、SubmissionとTimingを固定する。
3. 背景処理でBSOR encodeとgzipを行う。
4. QualifierResultFactoryが同一challengeId/clientResultIdのmetadataを作る。
5. Outboxへ永続化してからresult APIを呼ぶ。

| endType | endState / endAction | 結果の扱い |
|---|---|---|
| clear | cleared / none | 提出可能履歴とBSORがあれば採用候補 |
| fail | failed / none | clearと同様。Failを一律除外しない |
| quit | incomplete / quit | invalidReason=quit |
| restart | incomplete / restart | invalidReason=restarted |
| unknown | unknown / unknown | invalidReason=unknown |
| preflight_rejected | incomplete / none | invalidReason=preflight_rejected |

clear/failで提出禁止ならsubmission_disabled、それ以外でBSORがなければreplay_unavailable。gzip生成失敗や16 MiB超過でも、無効結果metadataは保持して提出する。終了種別による無効理由を提出禁止・Replay不足より優先する。

GameVersionにはApplication.versionのbuild suffixを含めて記録する。最大スコアは実ScoreControllerのmodifier modelと譜面から計算し、取得できない値を0で作らずnullにする。metadataの完全なfield、型、timing、diagnostics、BSOR上限はスコア管理API仕様を参照する。

仮サーバが確認するのはmetadata整合とBSOR構造・本人/MapKey識別までであり、BSORからスコアを再計算して採用判定する実装ではない。

## 13. Outbox

[QualifierOutbox.cs](../JBSLViewer.Qualifier.Core/Outbox/QualifierOutbox.cs)と[OutboxStore.cs](../JBSLViewer.Qualifier.Core/Outbox/OutboxStore.cs)を使用する。保存先はBeat SaberのUserData/JBSLViewer/QualifierOutbox。

各UUID.jsonへmetadata JSON、gzipバイト列（JSON内ではBase64）、challengeId、clientResultId、所有者SID、正規化送信先、結果期限、状態、再送回数、応答・エラーを保存する。

| 状態 | 意味 |
|---|---|
| save_failed | 永続化未完了。送信せず再保存を試みる |
| pending | 送信待ち・一時障害の再送待ち |
| sending | 送信中。再起動時はpendingへ戻す |
| awaiting_auth | 認証失敗後の明示再試行待ち |
| stopped | 恒久エラー、期限超過、不正応答等。データは保持 |
| sent | サーバの成功応答を保存済み |

未解決結果、保存失敗、最終化中、予約未解決、進行中challengeがある間は新規Challengeを止める。stoppedも未解決であり、自動的に捨てない。

### 13.1. 保存・送信先・再送

- 容量既定は1 GiB。新規確認時は使用量とディスク空きの双方に24 MiBの余裕を要求する。
- 一時ファイルへUTF-8 JSONを保存しFlush(true)した後、File.ReplaceまたはFile.Moveで置き換える。
- 壊れた保存ファイルはoutbox_corruptのstoppedとして読み込み、新規挑戦を止める。
- 送信直前にPersisted、所有者SID、現在認証session、保存したscoreServerBaseUrlを照合する。
- 接続先変更時はblockedReason=server_mismatch、SID違いはowner_mismatchとして保持する。元の設定へ戻すまで別サーバへ転送しない。
- 401では同じ所有者・接続先で最大1回再認証する。失敗後はawaiting_auth。
- 一時障害は指数backoff。基準1、2、4…最大60秒に0.8〜1.2倍のjitterを付ける。Retry-Afterがあれば優先する。
- result_acceptance_expired、challenge_timed_out、retryable=falseはstopped。クライアント時計の期限だけで結果を削除しない。
- 成功応答をまず永続保存し、次の保存で大きなmetadata/replay payloadを除去する。後段失敗時も成功記録とpayloadを保持する。

statusや予約の回復と同様、対象外譜面を選択中でも既存Outboxの再送は可能である。ネットワークへは同じmetadata・gzip・Idempotency-Keyを送る。

### 13.2. 手動操作と限界

設定画面から再試行・状態確認・未解決結果の強制クリアを行える。強制クリアは確認画面を経て、進行中challenge・PendingReserveがない場合に限り実行する。deleted.jsonの削除印を先に永続化してから対象ファイルを削除し、遅れて到着した最終化・保存処理による結果の復活を抑止する。

強制クリアはローカル結果の削除であり、サーバ側の回数返却や結果取消ではない。未送信結果を回復できなくなる操作である。

未永続化のsave_failedや、ゲームプロセスの強制終了前にまだ生成できていない結果は再起動後の回復を保証しない。永続Outboxとプロセス内の予約・最終化状態を区別する。

## 14. サーバ連携・期限

### 14.1. JBSL-WEB中継

mock_servers/jbsl_web_proxyは既存leaderboardへ保存fixtureを結合する。手動SID、既定ONのランキングSID自動追加、participants.name補完、BeatSaver曲時間補完を持つ。公開/qualifiers/でリーグ閲覧とSID追加を提供し、削除・置換・設定更新は管理認証後の操作になる。

Qualifier情報は現在のDjangoモデルへ直接追加したものではない。保存先、revision、公開登録の条件、管理Cookie/CSRF、公開HostはJBSL-WEB API仕様を参照する。

### 14.2. 仮スコア管理

mock_servers/score_managerの通常起動はstub認証・loopback限定。DBとBSOR、管理画面、障害注入、期限profile、cache、監査を持つ。公開ランキング、最高スコア集計、Replay公開、challenge強制終了・返却の管理機能はこの仮サーバにはない。

| 判定 | 現行既定 |
|---|---|
| score status cache | fresh 60秒、上流到達不能時の参考表示300秒 |
| 新規reserve | 成功済み同一キー以外は毎回上流を取得 |
| Viewer開始期限 | effectiveEnd - ローカルsongDuration以下 |
| 仮サーバ開始期限 | effectiveEnd以下。曲時間を引くprofileへ変更可 |
| 結果受付 | 予約時effectiveEnd + 300秒以下 |
| 結果判定時計 | resultハンドラー入口のサーバ受信時刻 |
| started | 期限を再判定しない。通知失敗で消費を戻さない |
| 同一result再送 | 受付期限内で同じ内容なら保存済み応答。期限後は拒否 |
| 残回数 | max(0, 現在上限 - 使用済み回数) |

結果がsubmittedでもvalidForRanking=falseの場合がある。HTTP 201は保存成功であり、採用可能スコアの証明とは別である。現在のクライアント・仮サーバは最高スコア集計を実行するコンポーネントをこの経路に持たない。

## 15. 設定と実行

[PluginConfig.cs](../JBSLViewer/Configuration/PluginConfig.cs)の主な既定値:

| 項目 | 値 |
|---|---|
| leaderboardApiUrl | https://jbsl-qualifier.rynan.com/leaderboard/api/ |
| activeLeagueApiUrl | https://jbsl-web.herokuapp.com/api/active_league |
| scoreServerBaseUrl | https://jbsl-score.rynan.com |
| allowDevelopmentHttp | false |
| qualifierRequestTimeoutSeconds | 30。Runtimeは5〜300秒へ制限 |
| refreshInterval | 10分 |

上記URLはソース内の既定値であり、今回の改訂で公開先の稼働を検証したという意味ではない。

ローカル仮サーバ接続用の設定例:

~~~json
{
  "leaderboardApiUrl": "http://127.0.0.1:18080/leaderboard/api/",
  "scoreServerBaseUrl": "http://127.0.0.1:18082",
  "allowDevelopmentHttp": true,
  "qualifierRequestTimeoutSeconds": 30
}
~~~

この設定例だけでは第16節のschema不一致は解消しない。fixtureを使った単体・契約試験と、現行中継応答を用いた連携試験を区別する。

| アプリ | API | 管理 | 通常保存先 |
|---|---|---|---|
| jbsl_web_proxy | 18080 | 18764 | data/control.json、data/admin_auth.sqlite3 |
| score_manager | 18082 | 18765 | data/control.json、data/score.sqlite3、data/replays/ |

各アプリは専用のrun.py、start.bat、setup.bat、verify.bat、配布スクリプトを持つ。中継は管理者初期化が必要。配布ZIPは明示したファイル一覧から作成し、運用DB、秘密設定、Replay、ログ、仮想環境を含めない。詳細は[中継README](../server/mock_servers/jbsl_web_proxy/README.md)、[仮スコアREADME](../server/mock_servers/score_manager/README.md)を参照する。

## 16. 実装間の不一致と保証範囲

| 項目 | 現行ソースの状態 |
|---|---|
| participants.name | 中継はnameを追加するが、指定仮スコアのvalidate_projectionはsidだけを要求する。直接連携はupstream_invalidになる |
| league_not_found status | 仮スコアはcache.fetchedAt=nullを返すが、ViewerのParseStatusは日時文字列を要求する |
| 時刻表記・map title | 中継のPython validationよりViewerが厳しい項目がある。UTC表記と文字列titleを揃える |
| BSOR検証 | basic_identity_only。スコア・modifier・時刻・gameVersionの相互照合やスコア再計算は行わない |
| revision | 中継の動的SID追加・名前補完などで増えない |
| 予約の永続化 | PendingReserveはプロセス内。永続Outboxと同じ回復保証はない |
| ファイルとDB | 仮サーバのReplayファイル保存とSQLite commitは別資源。プロセス強制終了時の完全原子性は保証しない |

今回の作業はこの不一致を含めて文書を整合させるものであり、アプリケーションコードを修正したものではない。エラーの発生条件を確認せずに「完成版だから全経路が接続可能」と扱わない。

## 17. 検証・保守・ライセンス

[共通C#試験プロジェクト](../JBSLViewer.Qualifier.Tests/JBSLViewer.Qualifier.Tests.csproj)は.NET Framework 4.8で、共通Coreと一部の実装を参照する。

| 確認領域 | 主な既存試験 |
|---|---|
| gate・認証・予約・終了 | CoreScenarios、AdditionalScenarios |
| Outbox・所有者・送信先 | OutboxScenarios |
| HTTP契約 | HttpContractScenarios |
| BSOR・Replay判定 | ReplayScenarios、ReplayModeScenarios |
| 専用画面・直接起動 | QualifierScreenScenarios、QualifierLaunchScenarios |
| ランキングcache・ページ | LeaderboardCacheScenarios、LeaderboardPagingScenarios |
| Python仮スコア | mock_servers/score_manager/tests |
| Python中継・管理・公開登録 | mock_servers/jbsl_web_proxy/tests |

APIレスポンス、deadline、snapshot、同時予約、型、BSOR、Outbox、画面世代をそれぞれ確認する。試験ファイルの存在、今回の文書検証、Releaseビルド、Beat Saber実機試験、公開環境の連携試験は別の証拠として記録する。

文書改訂の確認は、3文書のAPI・field・設定・状態が指定ソースに対応すること、JSON例が構文・対応schemaに合うこと、参照先が存在すること、実装前の前提を完成済みと誤記していないことを対象とする。

TA由来の専用画面・直接起動部分とBeatLeader由来のRecorder等には出典・MIT表示がある。[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)、[THIRD-PARTY-NOTICES.txt](../THIRD-PARTY-NOTICES.txt)、各ファイル先頭の表示を保守時にも保持する。

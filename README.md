# JBSLViewer
このBeatSaberプラグインは[JBSL-Web](https://jbsl-web.herokuapp.com/)の情報を表示します。

**Quest版を使用の方は、[JBSLViewerQuest](https://github.com/rynan4818/JBSLViewerQuest)** を使用してください。

![image](https://github.com/user-attachments/assets/03c01179-40c5-45e3-a5e4-eee59ba9d157)

現在は、Live Leaguesのリーダーボードを表示する機能があります。

## 特徴
* Headlinesの最新更新日時を基準にして、10分毎に自動更新します

# インストール方法
1. [リリースページ](https://github.com/rynan4818/JBSLViewer/releases)最新のJBSLViewerのリリースをダウンロードします。
2. ダウンロードしたzipファイルを`Beat Saber`フォルダに解凍して、`Plugin`フォルダに`JBSLViewer.dll`ファイルをコピーします。
3. [LeaderboardCore](https://github.com/rithik-b/LeaderboardCore)に依存するので、Mod Assistantでインストールして下さい。[BeatLeader](https://github.com/BeatLeader/beatleader-mod) modをインストールしている人は既に導入されています。

# 使い方
右のリーダーボードにJBSL-Webのリーダーボードが追加されます。

* `LEAGUE RELOAD`ボタンはLive Leaguesのリストを更新したい場合に使用します。同時にHeadlinesの最新更新日時も取得し直します。
* `BOARD RELOAD`ボタンは手動でLeaderboardを更新したい場合に押します。
* `Auto Reload Time`は次回更新までの時間です。
* `JBSL League`ドロップダウンはリーグを選択します。
* `Leaderboard`ドロップダウンはリーダーボードを選択します。
* `TOTAL`ボタンはリーダーボードを合計順位に切り替えます。
* `🔼`ボタンは前のページに移動します。
* `🔽`ボタンは次のページに移動します。

# 今後追加予定の機能
* ~~選択中譜面とリーダーボードの連動~~
* ユーザーアイコンの表示
* 自分のスコアをハイライト表示
* プレイリストダウンロード機能
* 終了したリーグの閲覧機能

# Qualifier（BS1.39.1専用ブランチ）

このブランチはBeat Saber **1.39.1**用です。`BS1.29.1`の`9c3fc19`（Qualifier機能仮搭載1）をmainの譜面APIへ移植しました。1.37.1系・1.40.8系・1.42.0系はそれぞれ専用ブランチで扱い、版をまたぐ実行時切り替えは行いません。詳細は[互換性と検証](docs/COMPATIBILITY.md)を参照してください。

`docs`のRevision 9に対応する、試行回数制限付きの挑戦機能を追加しています。通常のSolo Free Playで、実参加者・対象MapKey・受付期間・ローカル曲時間による開始期限が条件を満たすと、JBSLのパネルに`CHALLENGE`が表示されます。既存のランキングcacheを使用し、曲の選択ごとにJBSL-WEBを再取得しません。

確認画面の`CONFIRM`後、スコア管理サーバで予約が成功すると1回消費し、標準Playを開始します。Quit、Restart、開始失敗による返却はありません。通常のPauseや標準Modifierは使用できます。提出禁止状態はBS UtilsとSiraUtilの現在値から判定します。

結果はBSORとともに`UserData/JBSLViewer/QualifierOutbox`へ先に保存してから送信します。送信待ち・保存失敗・認証待ち・送信停止の結果がある間、新しいChallengeは開始できません。通常Playは利用できます。設定画面の`RETRY / REAUTHENTICATE`で保存・認証・送信を再試行できます。`CLEAR LOCAL RESULTS...`は確認後にローカルの未解決結果を破棄し、消費回数やサーバ保存済み結果は変更しません。

送信停止の`stopped`は`RETRY / REAUTHENTICATE`の再送対象外です。サーバ管理画面でチャレンジを強制終了しても、Viewerのローカル未解決結果は残るため、`Unresolved result — open settings`とChallengeの無効状態は解消しません。対象チャレンジが強制終了済みでローカル結果を破棄する場合は、Mod設定の`JBSLViewer`を開き、`Qualifier results`の状態とエラーを確認して、`CLEAR LOCAL RESULTS...` → `CLEAR`を実行してから曲選択へ戻ってください。ゲーム再起動でも送信停止記録は保持されます。

予約とClear・Fail結果の`gameVersion`は実ゲームのバージョン（例：`1.39.1_1715`）をビルド番号ごと保持します。プレイ開始前に失敗した結果も予約時の版を保持し、録画結果ではBSORと一致する実測値を使います。旧版でバージョン不一致により`replay_mismatch`となった既存の送信停止記録は、DLL更新だけでは変更されません。

結果の所有者と送信先は予約時点で固定されます。URLを変更すると旧送信先の結果は`server_mismatch`で保留され、別サーバへ送り替えません。元のURLへ戻すと元の状態に従って復旧します。Cookieや認証ticketはOutboxへ保存しません。起動をまたぐ結果復旧は永続保存できた結果が対象です。応答不明のreserveは起動をまたいで再送しません。

## 設定と仮サーバ

`scoreServerBaseUrl`の初期値は空です。ゲームのJBSLViewer設定で、利用するスコア管理サーバのHTTPS URLを設定してください。ローカルのPython仮サーバは、このリポジトリの1階層上にある`mock_servers`です。起動・fixture・認証modeは[`mock_servers/README.md`](../mock_servers/README.md)を参照してください。

開発用HTTPを使うときのMod設定例です。

```json
{
  "leaderboardApiUrl": "http://127.0.0.1:18080/leaderboard/api/",
  "scoreServerBaseUrl": "http://127.0.0.1:18081/",
  "allowDevelopmentHttp": true,
  "qualifierRequestTimeoutSeconds": 30
}
```

中継へ向ける既存APIは`leaderboardApiUrl`だけです。active league一覧・playlist・headlinesのURLは既存の設定を使います。`localhost`と`127.0.0.1`、port、base pathが異なるURLは別の送信先として扱います。

同梱fixtureは通信検証用です。ゲーム内で試す場合は、実際に選択可能なリーグ、参加者のplatform SID、インストール済み譜面のhash・characteristic・difficultyに合わせたfixtureを別途設定してください。stub認証の`JBSL_MOCK_SID`も実プレイヤーのSIDと一致させます。不一致のままではChallengeを開始できません。

## ビルドとゲーム外検証

Visual StudioのMSBuild、.NET Framework 4.8開発ツール、およびBeat Saber 1.39.1の参照DLLが必要です。`JBSLViewer.Qualifier.Core`はこのブランチ内でModとConsoleへソースを取り込み、Core専用DLLの配布は不要です。Consoleは署名済みのNuGet版Newtonsoft.Jsonを使い、通信・認証・進行状態・Outbox・BSOR形式を検証します。

Visual Studioでは`JBSLViewer.sln`を開くと、共有プロジェクト`JBSLViewer.Qualifier.Core`がソリューションエクスプローラーに表示されます。CoreのソースはModとConsoleに直接コンパイルされます。

ゲームへの自動コピーを有効にするには、ローカル設定`JBSLViewer/JBSLViewer.csproj.user`の`PropertyGroup`に`<DisableCopyToGame>False</DisableCopyToGame>`を追加し、`BeatSaberDir`にゲームのインストール先を指定します。ビルド成功時にゲームの`Plugins`へDLLがコピーされます。このユーザー設定ファイルはGit管理対象外です。検証などでコピーを止める場合はMSBuildに`/p:DisableCopyToGame=True`を指定してください。

このリポジトリのルートから実行します。`build.ps1`はReleaseビルド、C#テスト、実DLLに対するAPI照合、配布ZIPの作成を行います。ゲームへのコピーは行いません。

```powershell
.\build.ps1
# 本体とMod参照を別フォルダーから読む場合
.\build.ps1 -GameDirectory 'C:\Program Files (x86)\Steam\steamapps\common\Beat Saber' `
    -ModReferencesDir 'C:\Program Files (x86)\Steam\steamapps\common\Beat Saber_1.39.1SS'
```

NuGetが利用できない環境では、既存のpackage cacheを`-LocalNuGetFeed`へ指定できます。`-MSBuildPath`とAPI照合用の`-CecilPath`も指定可能です。API照合はUnityを起動せず、実DLLのメンバー参照、Harmonyの引数名、privateフィールドの型を確認します。

DLLは`JBSLViewer/bin/Release/JBSLViewer.dll`、配布ZIP・検証ログ・SHA256は`artifacts/BS1.39.1/<日時>/`へ出力します。ZIPには`Plugins/JBSLViewer.dll`と`THIRD-PARTY-NOTICES.txt`を同梱します。Modのバージョンは0.4.0です。

仮サーバのvenvを準備した後、次のコマンドでローカルHTTP試験を実行できます。試験用DBは毎回隔離され、スクリプトが起動した仮サーバだけを終了します。別worktreeでは`-MockWorkspace`に`mock_servers`を含む作業ルートを指定してください。

```powershell
.\JBSLViewer.Qualifier.Tests\run_http_probe.ps1 -MockWorkspace '..'
```

ゲーム内でのUI配置、Steam/Oculus実認証、他Mod併用、実トラッキングの録画品質は実機プレイでの確認が必要です。今回の自動検証範囲は[互換性と検証](docs/COMPATIBILITY.md)に記録しています。

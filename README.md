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

# Qualifier（BS1.42.0専用ブランチ）

このブランチはBeat Saber **1.42.0～1.44.1**用です。`BS1.29.1`の`addb99d`（チャレンジ専用画面とTA方式の直接プレイ開始）までを各版の譜面APIへ移植しました。他の対象版はそれぞれ専用ブランチで扱い、版をまたぐ実行時切り替えは行いません。新しい`IPlatform`認証APIを直接使用します。今回のTA由来の変更と対象版の確認は[チャレンジ移植記録](docs/TA_CHALLENGE_PORT.md)、以前の対応範囲は[互換性と検証](docs/COMPATIBILITY.md)を参照してください。

試行回数制限付きの挑戦機能は、メインメニューのModボタン`JBSL CHALLENGE`から開く専用画面で利用できます。`リーグ一覧 → 対象曲一覧 → 曲詳細`の順に選びます。通常SoloのJBSLパネルにある`CHALLENGE`からも、現在のリーグ・対象譜面を引き継いで開けます。

TournamentAssistantのQualifier画面を基に、中央にジャケット・曲情報・指定難易度、左に標準プレイヤー設定とModifiers、右にJBSLランキング、下に残り回数と状態を表示します。曲のCharacteristicと難易度はリーグ指定に固定されます。未導入の曲はインストール後に`RELOAD`してください。非対応リーグ・参加対象外・受付終了・残数0・認証や送信待ちは画面に理由を表示し、新しいChallengeを開始できない状態にします。

曲詳細の`CHALLENGE`で確認画面を開き、`CONFIRM`による予約後に指定譜面のプレイを直接開始します。`PRACTICE`もTAと同様に曲の最初から通常プレイを直接開始し、予約や回数消費、JBSLへのチャレンジ結果送信を行いません。標準Practiceの開始位置・速度指定画面は開きません。

Clear / Failでは専用画面内に標準のリザルトUIを表示し、`CONTINUE`で同じ曲詳細へ戻ります。Quitではそのまま曲詳細へ戻ります。PRACTICEのリザルトでは`RESTART`で回数を消費せず再開できます。本番のリザルトではRESTARTを無効にし、次の挑戦は曲詳細から確認・予約を行います。戻る操作は曲詳細→曲一覧→リーグ一覧→メニューの順です。

既存のランキングキャッシュを共有し、参加資格・譜面・受付時刻と曲時間・提出可否を確認します。予約後は専用画面の選択譜面・プレイヤー・リーグ・提出可否を再照合し、TAと同じ`MenuTransitionsHelper.StartStandardLevel`で開始します。開始時も終了後もソロ選曲画面へ移動せず、入室時の画面階層と譜面選択を維持します。

右側のランキングは通常Soloで使っているJBSLViewerの表示を共用し、順位・名前・POS・ACC・FC/MISS・色分けを引き継ぎます。リーグの譜面一覧ではそのリーグの`TOTAL`、曲詳細では選んだ曲・Characteristic・難易度に一致する順位を表示します。曲詳細から一覧へ戻ると`TOTAL`に戻り、リーグ一覧へ戻ると右側を閉じます。譜面の読み込み中や未導入の場合も、一覧では`TOTAL`を表示します。

上下ボタンで10件ずつページを送れます。先頭では上、末尾では下、10件以下では両方のボタンが無効になります。同じランキングの更新ではページを維持し、件数が減った場合は有効な最終ページへ戻します。表示対象を変えると先頭へ戻ります。通常Soloのパネルで選択中のリーグ・曲や保存設定は変更しません。

未参加リーグを選ぶと、曲一覧へ進む前に「未参加のリーグ」「このリーグには参加していません。」を表示します。`OK`または戻る操作で閉じて選び直せます。スコア未提出でも参加者登録があれば入室できます。アカウント未取得やリーグ情報の読込失敗、非対応リーグにはそれぞれ別の案内を表示します。

直接開始の準備中は二重操作を抑止し、ゲームへの遷移が確定する前なら戻るボタン`<`で中止できます。予約済みの試行回数は返却されません。開始時の例外では曲詳細へ戻り、状態を表示します。ログの`Challenge launch:`に準備と直接開始を記録します。

画面の流用元は[TournamentAssistant（MIT License）](https://github.com/MatrikMoon/TournamentAssistant?tab=MIT-1-ov-file)です。流用したC#・BSMLの先頭にライセンス全文と出典を記載し、配布物の`THIRD-PARTY-NOTICES.txt`にも収録しています。

確認画面の`CONFIRM`後、スコア管理サーバで予約が成功すると1回消費し、標準Playを開始します。Quit、Restart、開始失敗による返却はありません。通常のPauseや標準Modifierは使用できます。提出禁止状態はBS UtilsとSiraUtilの現在値から判定します。

結果はBSORとともに`UserData/JBSLViewer/QualifierOutbox`へ先に保存してから送信します。送信待ち・保存失敗・認証待ち・送信停止の結果がある間、新しいChallengeは開始できません。通常Playは利用できます。設定画面の`RETRY / REAUTHENTICATE`で保存・認証・送信を再試行できます。`CLEAR LOCAL RESULTS...`は確認後にローカルの未解決結果を破棄し、消費回数やサーバ保存済み結果は変更しません。

送信停止の`stopped`は`RETRY / REAUTHENTICATE`の再送対象外です。サーバ管理画面でチャレンジを強制終了しても、Viewerのローカル未解決結果は残るため、`Unresolved result — open settings`とChallengeの無効状態は解消しません。対象チャレンジが強制終了済みでローカル結果を破棄する場合は、Mod設定の`JBSLViewer`を開き、`Qualifier results`の状態とエラーを確認して、`CLEAR LOCAL RESULTS...` → `CLEAR`を実行してから曲選択へ戻ってください。ゲーム再起動でも送信停止記録は保持されます。

予約とClear・Fail結果の`gameVersion`は実ゲームのバージョン（例：`1.42.0_12297`）をビルド番号ごと保持します。プレイ開始前に失敗した結果も予約時の版を保持し、録画結果ではBSORと一致する実測値を使います。旧版でバージョン不一致により`replay_mismatch`となった既存の送信停止記録は、DLL更新だけでは変更されません。

結果の所有者と送信先は予約時点で固定されます。URLを変更すると旧送信先の結果は`server_mismatch`で保留され、別サーバへ送り替えません。元のURLへ戻すと元の状態に従って復旧します。Cookieや認証ticketはOutboxへ保存しません。起動をまたぐ結果復旧は永続保存できた結果が対象です。応答不明のreserveは起動をまたいで再送しません。

## 仕様書

以下はRevision 10の共通資料です。調査基準はBS1.39.1版と仮サーバで、各版の対応範囲・差分はこのREADMEを参照してください。

- [スコア管理サーバAPI仕様書](docs/JBSL_Qualifier_Score_Manager_API_Specification.md)
- [Qualifier全体設計仕様書](docs/JBSL_Qualifier_Design_For_GPT-5.6Sol.md)
- [JBSL-WEB Qualifier API仕様書](docs/JBSL_WEB_Qualifier_API_Specification.md)

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

Visual StudioのMSBuild、.NET Framework 4.8開発ツール、およびBeat Saber 1.42.0の参照DLLが必要です。`JBSLViewer.Qualifier.Core`はこのブランチ内でModとConsoleへソースを取り込み、Core専用DLLの配布は不要です。Consoleは署名済みのNuGet版Newtonsoft.Jsonを使い、通信・認証・進行状態・Outbox・BSOR形式を検証します。

Visual Studioでは`JBSLViewer.sln`を開くと、共有プロジェクト`JBSLViewer.Qualifier.Core`がソリューションエクスプローラーに表示されます。CoreのソースはModとConsoleに直接コンパイルされます。

ゲームへの自動コピーを有効にするには、ローカル設定`JBSLViewer/JBSLViewer.csproj.user`の`PropertyGroup`に`<DisableCopyToGame>False</DisableCopyToGame>`を追加し、`BeatSaberDir`にゲームのインストール先を指定します。ビルド成功時にゲームの`Plugins`へDLLがコピーされます。このユーザー設定ファイルはGit管理対象外です。検証などでコピーを止める場合はMSBuildに`/p:DisableCopyToGame=True`を指定してください。

このリポジトリのルートから実行します。`build.ps1`はReleaseビルド、C#テスト、実DLLに対するAPI照合、配布ZIPの作成を行います。ゲームへのコピーは行いません。

```powershell
.\build.ps1
# 本体とMod参照を別フォルダーから読む場合
.\build.ps1 -GameDirectory 'C:\Program Files (x86)\Steam\steamapps\common\Beat Saber_1.42.0' `
    -ModReferencesDir 'C:\Program Files (x86)\Steam\steamapps\common\Beat Saber_1.42.3'
```

NuGetが利用できない環境では、既存のpackage cacheを`-LocalNuGetFeed`へ指定できます。`-MSBuildPath`とAPI照合用の`-CecilPath`も指定可能です。API照合はUnityを起動せず、実DLLのメンバー参照、Harmonyの引数名、privateフィールドの型を確認します。

DLLは`JBSLViewer/bin/Release/JBSLViewer.dll`、配布ZIP・検証ログ・SHA256は`artifacts/BS1.42.0/<日時>/`へ出力します。ZIPには`Plugins/JBSLViewer.dll`と`THIRD-PARTY-NOTICES.txt`を同梱します。Modのバージョンは0.4.0です。

仮サーバのvenvを準備した後、次のコマンドでローカルHTTP試験を実行できます。試験用DBは毎回隔離され、スクリプトが起動した仮サーバだけを終了します。別worktreeでは`-MockWorkspace`に`mock_servers`を含む作業ルートを指定してください。

```powershell
.\JBSLViewer.Qualifier.Tests\run_http_probe.ps1 -MockWorkspace '..'
```

ゲーム内でのUI配置、Steam/Oculus実認証、他Mod併用、実トラッキングの録画品質は実機プレイでの確認が必要です。今回の自動検証範囲は[互換性と検証](docs/COMPATIBILITY.md)に記録しています。

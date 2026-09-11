# JBSL Score Server

JBSLViewerのQualifier APIに合わせた、Python製のスコア管理サーバです。APIと管理画面を別ポートで起動し、予約・提出・回数・Replay・操作履歴をSQLiteへ保存します。既存の `mock_servers`、JBSLViewer Mod、ゲームDLLには実行時依存しません。

## Windowsで起動

1. Python **3.12以上**をインストールします。既存Pythonを指定する場合は `JBSL_PYTHON` に `python.exe` の絶対パスを設定します。
2. このフォルダの **`start.bat`** を実行します。初回は専用仮想環境と必要パッケージを用意します。初回の取得にはインターネット接続が必要です。
3. 初回だけ管理者名と12文字以上のパスワードを入力します。パスワードの既定値はありません。
4. **http://127.0.0.1:18763/admin/** をブラウザで開きます。

| 用途 | 既定の待受 |
|---|---|
| Viewer・jbsl-web用API | `127.0.0.1:18081` |
| 管理画面（専用ポート） | `127.0.0.1:18763` |

`Ctrl+C` で両方を停止します。設定とデータは次回起動後も保持されます。2回目以降、固定依存関係が導入済みなら起動時のネットワーク取得は行いません。仮想環境を別PCへ移す場合は `.venv` を移さず、移動先で `setup.bat` を実行してください。

起動設定は初回に作成する `config.json`、変更可能な運用設定は管理画面から保存するDB内の設定です。ポートや接続先の変更後はサーバを再起動します。運用設定は再起動せず反映されます。

別の起動設定を使う場合は、環境変数 `JBSL_CONFIG` にそのJSONファイルの絶対パスを設定して `start.bat` を実行できます。

## ログイン不要のランキング

ログイン画面の **「ランキング表示（ログイン不要）」** から、閲覧専用のランキングを開けます。既定URLは **http://127.0.0.1:18763/admin/rankings/** で、直接開くこともできます。

リーグ・譜面を選ぶと、順位、表示名・SID、最高スコア・精度、残回数、提出日時・結果、回数上限・曲時間を表示します。各行の「リプレイ」列に **DL（`.bsor.gz`のダウンロード）・BeatLeader・ArcViewerでの再生** の小さな3操作を横並びで表示します。公開Replayはログイン不要で、取得時点でランキングに採用されている提出に限ります。最新情報はブラウザの再読み込みで取得し、「ログイン画面へ」リンクで戻れます。更新を適用するにはサーバを再起動してください。

## 管理画面

- ログイン画面と管理メニューの **「API仕様（Swagger UI）」** から、全API操作の認証・パラメーター・送信形式・応答を閲覧できます。既定URLは **http://127.0.0.1:18763/admin/docs/**。仕様の閲覧はログイン不要、実行ボタンは無効です。
- 各項目の **「?」** で説明ポップアップを開きます。設定値の単位・初期値・範囲・適用時点、状態・回数・ログ・取消復元の意味を確認できます。キーボードのEnterで開き、Escapeで閉じられます。
- **「図付き運用ガイド」** は **http://127.0.0.1:18763/admin/guide/**。期限、返却条件、Challengeの状態、回数、取消復元、JBSL-WEB連携、バックアップを説明します。猶予を入力する受付期限の計算例は、サーバ設定を変更しません。

説明ページは別タブで開くため、管理画面の入力を保持できます。Swagger UI・図・説明のファイルはすべて同梱し、閲覧時は外部CDN・外部validatorへ接続しません。起動済みサーバへこの変更を適用する場合は、一度サーバを再起動してください。

- **概要**: 予約・プレイ中・提出済み件数、最近の提出、受信・操作ログ、空き容量、バックアップ、上流キャッシュ。15秒ごとに更新します。
- **ランキング**: リーグ・譜面を選び、ユーザーごとの有効な最高スコアを降順表示。同点は1,1,3順位です。「ユーザー・提出履歴」で残回数・全提出とチャレンジ操作、「詳細・取消・復元」で採用した提出とReplayを確認できます。行の「1回返却」でその提出の消費回数を返却します。取消時は次点を自動採用し、取消済み提出の復元はユーザーの提出履歴から行えます。操作後やユーザー画面から戻った後もリーグ・譜面の選択を保持します。
- **Challenge・提出**: SID、League、状態で絞り込み。結果の詳細、Replay取得、BeatLeader / ArcViewerでの再生、取消・復元。
- **ユーザー**: ユーザー検索、譜面ごとの使用回数・返却数・残回数、全Challengeと提出結果。
- **操作・受信ログ**: 提出成功・拒否、期限終了、回数返却、設定変更、管理操作。受付・操作開始からログ記録までの所要時間（ms）を表示します。過去の未計測ログは「—」。ページ送り対応。
- **サーバ設定**: 対象別の4カテゴリに整理しています。**JBSLViewer（mod）向け**は認証セッション・API要求数の制限、**jbsl-web連携**は上流情報のキャッシュ、**共通（大会運用）**は受付・期限・同時Challenge数・回数返却、**スコア管理サーバ固有**はディスク空き下限・バックアップです。共通のルールはViewerの予約・提出と、jbsl-webに渡す回数情報に関わり、スコア管理サーバで判定・管理します。変更は画面下部の「設定を保存」でまとめて保存します。

回数返却は「開始前失敗」「開始を観測した失敗」「Quit」「Restart」「不明」「標準提出無効」「Replay生成失敗」「結果未着・タイムアウト」から選べます。**既定はすべて返却しません**。申告された終了理由に基づくため、返却を有効にする際は繰り返し利用できる条件になることを考慮してください。

猶予・タイムアウト・返却条件は予約時に固定します。後から設定を変えても、進行中のChallengeの期限や返却ルールは変わりません。取消・復元は理由を必須とし、元データと履歴を残します。回数を追加で消費・返却する操作ではありません。元々ランキング対象外の結果を復元しても対象外のままです。

## Replayのブラウザ再生

Replayの外部再生は `api_public_url` がHTTPSの場合に利用できます。提出結果からビューアを選ぶと、そのReplayだけを取得できる最長10分の閲覧URLを発行します。管理者ログアウトでも失効します。対応する譜面・音源の取得が必要です。設定の詳細は [OPERATIONS.md](docs/OPERATIONS.md#外部ビューアでの再生) を参照してください。

公開ランキングの再生リンクはログインやトークンを使わず、現在のランキング採用を配信時に確認します。HTTPS未設定の場合は2つの再生ボタンが無効になり、Replayダウンロードを利用できます。公開用の `/api/v1/public/replays/` をAPI listenerへ中継してください。

## チャレンジの強制終了・手動返却

管理画面の **「ユーザー」→「提出状況を確認」** で、対象チャレンジ行の **「強制終了」** または **「1回返却」** を選び、理由を入力して実行します。「Challenge・提出」と概要の一覧からも操作できます。

- **強制終了**: 予約済み・プレイ中を終了し、その後の開始通知・結果提出を拒否します。「同時に1回返却する」を選ぶと、終了と返却をまとめて確定します。初期値は返却なしです。
- **1回返却**: 提出済み・未提出終了の消費1回を手動で返却します。自動返却設定がOFFでも使用でき、自動・手動を合計して1チャレンジにつき最大1回です。提出済みスコアやReplay、ランキングの採否は維持します。
- 実行後に状態・使用回数・返却数・残回数を更新し、管理者名と理由を操作履歴へ記録します。返却なしで強制終了したものは、後からの期限処理でも自動返却しません。

強制終了はサーバの受付を終了する操作です。参加者のゲームやViewerのローカル送信待ち記録は操作しません。結果提出が先に確定していた場合は強制終了を拒否するため、最新状態を確認してください。起動済みサーバへの適用にはサーバの再起動と管理画面の再読み込みが必要です。

## JBSLViewer・jbsl-webとの接続

Viewerは `scoreServerBaseUrl` にスコアAPIのURLを設定します。ローカルHTTPで試すときだけViewerの `allowDevelopmentHttp=true` が必要です。本番はHTTPSを指定します。APIのパス、Cookie名、フォーム・multipart形式、再送規則は現行Viewerに合わせています。

本番の認証はSteam/Oculusの実provider検証です。Steam APIキーは `config.json` の `steam_api_key`、または環境変数 `JBSL_STEAM_API_KEY` に設定します。Oculusは現行Viewerが取得するアクセストークンを `graph.oculus.com/me` で検証します。認証用の固定ユーザー・無条件許可モードは本番ランチャーにありません。

`jbsl_web_url` の `GET /leaderboard/api/{leagueId}` から、既存仕様書のQualifier拡張情報を取得します。上流にも認証が必要な場合は `jbsl_web_token` または `JBSL_JBSL_WEB_TOKEN` を設定します。新規予約は毎回最新の上流を検証し、上流障害・不正応答の際には回数を消費しません。予約済みの結果提出は上流の復旧を待たず受け付けます。

表示名がSIDのユーザーは、上流の `participants[].sid/name` で名前を補完します。名前が得られない場合は `total_rank`、譜面別 `scores` の順に参照します。通常の上流取得や管理者のリーグ情報更新時に既存ユーザーへ反映し、ログイン時にも保存済みの名前を利用します。SIDと異なる既存名は保持します。名前が欠けた旧形式も受け付け、参加資格はSIDで照合します。

jbsl-webが結果を取得するためのトークンを作成します。

```bat
.venv\Scripts\python.exe -m jbsl_score create-token jbsl-web
```

表示されたトークンをjbsl-web側の秘密設定へ保存してください。結果・取消・復元の差分取得、ランキング、ユーザーの残回数を取得できます。[API仕様と取り込み方法](docs/API.md)を参照してください。**jbsl-web側のQualifier拡張および結果取り込みは、接続先側の実装が必要です**。このフォルダはそのためのサーバAPIと取り込み用クライアントを提供します。

## 検証

```bat
verify.bat
```

Pythonテスト、既存Viewerソースのゲーム非依存C#テスト、実HTTP上の認証・予約・開始・BSOR提出・100件同時予約、管理画面のログイン・設定保存・ユーザー履歴・取消復元・ログアウト、DB/Replayのバックアップと復元を順に検証します。**ゲームDLLは不要**です。C#検証には.NET 8以降のSDK、ブラウザ検証にはWindowsのEdgeが必要です。検証用の架空ユーザーと専用DBを使用し、Steam・Oculus・実jbsl-webへは接続しません。

結果は `validation/latest/<日時-ID>/summary.json`、各ログ、JUnit XML、管理画面のPNGへ保存します。`passed` 以外、またはブラウザを明示的に省略した記録は全項目完了の記録ではありません。`verify.bat` 自体は依存関係取得のためネット接続します。導入後は `.venv\Scripts\python.exe scripts\validate.py` でオフライン検証できます。

一括検証にはSwagger全API操作の描画、外部接続なしでの表示、説明ポップアップとフォーカス復帰、設定を変えずにヘルプを開けること、詳細画面内からの説明表示、ガイドのリンク先・計算例・モバイル表示の確認も含みます。

ランキング画面の絞り込み・同点順位・ユーザー履歴への移動・取消時の繰上げ・復元・返却も専用データで検証します。単独で実行する場合は `.venv\Scripts\python.exe scripts\validate_rankings.py --output validation\rankings-check` を使用し、出力先にはまだ存在しないフォルダを指定してください。

Pythonだけを実行する場合:

```bat
.venv\Scripts\python.exe -m pytest -q
```

検証は上記の `verify.bat` またはPythonテストを実行してください。一括検証は、このリポジトリの同じQualifierブランチにあるC#テストも使用します。[サーバー全体の案内](../README.md)と[設計・運用手順](docs/OPERATIONS.md)も参照してください。

## バックアップ・保守

```bat
.venv\Scripts\python.exe -m jbsl_score backup
.venv\Scripts\python.exe -m jbsl_score check
.venv\Scripts\python.exe -m jbsl_score set-admin admin
.venv\Scripts\python.exe -m jbsl_score revoke-token jbsl-web
```

バックアップは `data/backups`、ローテーションするエラーログは `data/logs` です。ライブDBのファイルを直接コピーせず、上記のバックアップ機能を使用します。復元は別の新しいフォルダへ行います。

```bat
.venv\Scripts\python.exe -m jbsl_score restore data\backups\score-YYYYMMDD-HHMMSS-xxxxxxxx.sqlite3 data-restored
```

復元後はログインセッションとサービス用トークンを失効させます。停止後に `config.json` の `data_dir` を復元先に変更し、サービス用トークンを再発行して起動してください。設定ファイルと環境変数内の秘密情報はDBバックアップに含まれません。

この構成の対象は、単一Windows/Linuxホスト上の小規模運用です。公開APIにはHTTPS、専用OSユーザーのファイル権限、定期的な別媒体へのバックアップ、プロセス監視を設定してください。管理ポートは既定でloopback限定です。詳細は[運用手順](docs/OPERATIONS.md)にまとめています。

## 配布用ZIPの作成

`make_zip.bat` をダブルクリックするか、このフォルダで実行します。`dist/` に日時と識別子付きのZIPを新しく作成し、収録した全ファイルのSHA-256を検証します。既存のZIPは上書きしません。ZIP作成にはWindows標準のPowerShell/.NETだけを使います。

```bat
make_zip.bat
make_zip.bat -OutputDirectory "C:\temp\JBSL 配布"
```

現在の設定・DB・リプレイ・ログ・仮想環境・テスト・過去のZIPは含めません。配布先はZIPをフォルダごと展開し、同梱の `README.md` に従って `start.bat` を実行します。初回の依存パッケージ導入にはPythonとネット接続が必要です。

収録対象は [package-files.json](package-files.json) の明示的な一覧です。実行に必要なファイルを追加・改名した場合は、この一覧も更新してください。一覧外のファイルは、任意の名前で保存したデータも含めて収録しません。必要なファイルが欠けていれば作成を中止します。配布用READMEの原稿は [DISTRIBUTION.md](DISTRIBUTION.md) です。検証用コードとZIP作成ツール自体は、導入用ZIPには含めません。

## Linux / systemd での起動・停止

Debian 12 / Python 3.13では、Windowsのbatを使わず、各アプリ専用の仮想環境を作ります。このアプリのフォルダで実行してください。uvは導入済みの前提です。

```bash
"$HOME/.local/bin/uv" venv --python 3.13 .venv
"$HOME/.local/bin/uv" pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -m jbsl_score init
.venv/bin/python -m jbsl_score run
```

先にconfig.jsonの公開URL・接続先と管理者を設定してください。システムPythonの変更は不要です。2アプリの仮想環境は共有しません。

`deploy/systemd/jbsl-score.service` を同梱しています。UserとWorkingDirectory・ExecStartを実際の一般ユーザー・展開先に変更し、`/etc/systemd/system/` にコピーして登録します。実行ユーザーがuvのPython本体にもアクセスできることを確認してください。

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now jbsl-score
sudo systemctl status jbsl-score
sudo journalctl -u jbsl-score -n 100 --no-pager
sudo systemctl restart jbsl-score
```

両ポートの起動後に `ready` を出力します。Type=simpleのactive表示だけではアプリの準備完了を保証しないため、ログ・HTTP応答も確認します。SIGTERM・Ctrl+Cで両ポートを停止し、正常終了は0、起動失敗・想定外の待受終了・停止期限超過は非0終了です。異常終了は5秒後に再試行し、300秒内に5回の起動制限へ達すると停止します。原因修正後は `sudo systemctl reset-failed jbsl-score` と `sudo systemctl start jbsl-score` で再開します。手動stopでは自動再起動しません。

スコアのHTTP終了猶予は `request_timeout_seconds + 30` 秒です。`TimeoutStopSec` は `request_timeout_seconds + 90` 秒以上に合わせてください。 非同期の終了待ちにも上限を設けていますが、同期処理の停止を最終的に保証するのはsystemdのTimeoutStopSecです。停止期限内に完了しなかった要求の成功は保証しません。

LinuxではTIME_WAITが残っていても修正版同士の再起動が可能です。旧版はSO_REUSEADDRを使っていないため、旧版から初めて切り替える時だけ、停止後に約65秒待つ必要がある場合があります。同一ポートの二重起動は拒否します。同じdataを異なるポートで複数プロセスから操作しないでください。

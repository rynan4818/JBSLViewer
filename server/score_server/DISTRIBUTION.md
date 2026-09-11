# JBSL Score Server（配布版）

JBSLViewerのQualifier APIに対応したスコア管理サーバです。Python 3.12以上とWindowsを使用します。ゲームDLLと開発用リポジトリは不要です。

## 新規環境の構築

1. ZIPを展開し、`score_server` フォルダ全体を任意の場所へ置きます。
2. Python 3.12以上をインストールします。
3. `start.bat` を実行します。初回は `.venv` と必要パッケージを用意し、`config.example.json` から `config.json` を作成します。パッケージ取得にはインターネット接続が必要です。
4. 初回に管理者名と12文字以上のパスワードを入力します。パスワードの既定値はありません。
5. **http://127.0.0.1:18763/admin/** を開いてログインします。

APIは `http://127.0.0.1:18081`、管理画面は専用ポート18763です。Ctrl+Cで両方を終了します。設定とデータは次回起動後も保持します。

Pythonの場所を指定する場合はPowerShellで実行します。

```powershell
$env:JBSL_PYTHON = 'C:\Path\To\Python\python.exe'
.\start.bat
```

`setup.bat` は環境構築だけを実行します。既存のPython環境をコピーする必要はありません。配布ZIPには `config.json`、管理者、トークン、DB、リプレイ、バックアップは含まれていません。

## 接続設定

`config.json` のポート・公開URL・`jbsl_web_url` を使用環境に合わせます。Steamの認証には `steam_api_key` または環境変数 `JBSL_STEAM_API_KEY` を設定します。外部のJBSL-WEB接続にトークンが必要なら `jbsl_web_token` または `JBSL_JBSL_WEB_TOKEN` を設定します。設定変更後に再起動します。

中継サーバとローカルで組み合わせる場合の `jbsl_web_url` は `http://127.0.0.1:18080` です。Viewerの `scoreServerBaseUrl` はこの実スコアAPI（既定 `http://127.0.0.1:18081`）に設定します。ローカルHTTPではViewerの `allowDevelopmentHttp=true` を指定します。

初期状態の管理画面はループバックに限定しています。公開運用でのHTTPS、OS権限、監視、バックアップは [運用手順](docs/OPERATIONS.md) を参照してください。

## 管理・仕様・連携

ログイン画面の **「ランキング表示（ログイン不要）」** から **http://127.0.0.1:18763/admin/rankings/** を開けます。リーグ・譜面別の順位、表示名・SID、スコア・精度、残回数、提出日時・結果、回数上限・曲時間を表示する閲覧専用ページです。操作列とボタンはなく、最新情報はブラウザの再読み込みで取得します。URLの直接表示もログイン不要です。

管理画面からChallenge・提出・ユーザー・ログ・運用設定を確認できます。各項目の「?」と図付き運用ガイドを利用してください。

表示名がSIDのユーザーは、上流の `participants[].sid/name` を優先して名前を補完します。通常の上流取得・リーグ情報更新・保存済み情報によるログイン時に反映し、既にSIDと異なる名前は保持します。「操作・受信ログ」と概要の最近のログには、受付・操作開始からログ記録までの所要時間（ms）を表示します。過去の未計測ログは「—」です。

**「ランキング」** ではリーグ・譜面ごとにユーザーの有効な最高スコアを降順表示します。同点は1,1,3順位です。各行から **「ユーザー・提出履歴」**、**「詳細・取消・復元」**、**「1回返却」** を操作できます。取消後は次点の有効スコアを採用し、取消済みスコアはユーザーの提出履歴から復元できます。更新を適用するにはサーバを再起動し、管理画面を再読み込みしてください。

- Swagger UI: **http://127.0.0.1:18763/admin/docs/**。閲覧はログイン不要です。
- 図付きガイド: **http://127.0.0.1:18763/admin/guide/**。
- [API仕様とjbsl-webの取り込み方法](docs/API.md)。取り込み用クライアントは `integration_client.py` です。
- [同梱資産のライセンス](docs/THIRD_PARTY.md)。Swagger UIとライセンスは `jbsl_score/static/vendor/swagger-ui/` に同梱しています。

## 強制終了と手動返却

管理画面の **「ユーザー」→「提出状況を確認」** で、予約済み・プレイ中の **「強制終了」** を選びます。操作理由を入力し、必要なら **「同時に1回返却する」** を選んで確定してください。返却なしの強制終了では、使用回数を維持します。

終了済みの未返却チャレンジには **「1回返却」** を使用できます。自動返却設定がOFFでも使用でき、自動・手動を合計して1チャレンジにつき最大1回です。提出済みスコア・Replay・ランキングの採否を維持し、管理者名と理由を操作履歴へ記録します。

強制終了はサーバの開始通知・結果提出の受付を終了する機能です。参加者のゲームを遠隔停止する機能ではありません。起動済みサーバに更新を適用する際は、サーバを再起動して管理画面を再読み込みしてください。

## Replayのブラウザ再生

提出結果の「BeatLeaderで再生」「ArcViewerで再生」は、API公開URLをHTTPSに設定すると利用できます。対象Replayだけの閲覧用URLを選択した外部ビューアに渡し、別タブで再生します。URLは最長10分で失効し、管理者ログアウトでも失効します。譜面・音源を取得できることが必要です。詳細とDB版3への自動移行については [運用手順](docs/OPERATIONS.md#外部ビューアでの再生) を確認してください。

## 保守コマンド

このフォルダで実行します。

```bat
.venv\Scripts\python.exe -m jbsl_score check
.venv\Scripts\python.exe -m jbsl_score backup
.venv\Scripts\python.exe -m jbsl_score set-admin admin
.venv\Scripts\python.exe -m jbsl_score create-token jbsl-web
```

DBとリプレイは `data/`、バックアップは `data/backups/` に保存します。稼働中のDBを直接コピーする代わりに、上記のbackupコマンドを使用してください。復元とトークン失効の扱いは運用手順を参照してください。

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

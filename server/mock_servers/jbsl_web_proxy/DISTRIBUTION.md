# JBSL-WEB中継サーバ（配布版）

JBSLViewer用のローカルデバッグサーバです。Python 3.11以上とWindowsを使用します。ゲームDLLは不要です。

## 初回起動

1. ZIPを展開し、`jbsl_web_proxy` フォルダを任意の場所へ置きます。ZIP内から直接起動せず、フォルダ全体を展開してください。
2. Python 3.11以上をインストールします。
3. `start.bat` を実行します。初回は `.venv` を作成し、必要パッケージを取得します。初回だけインターネット接続が必要です。
4. 起動コンソールで管理者のユーザー名とパスワードを作成します。パスワードは12〜256文字で、入力中は表示されません。確認のため同じパスワードをもう一度入力します。
5. **http://127.0.0.1:18764/admin/** を開き、作成したユーザー名・パスワードでログインします。公開URLを設定している場合は、そのURLの `/admin/` を使用します。

APIは `http://127.0.0.1:18080`、Swagger UIは `http://127.0.0.1:18080/docs` です。Ctrl+CでAPIと専用管理画面を終了します。

Pythonの場所を指定する場合はPowerShellで実行します。

```powershell
$env:JBSL_PYTHON = 'C:\Path\To\Python\python.exe'
.\start.bat
```

別ポート・保存先を使う場合は `start.bat --api-port 19080 --admin-port 19764 --data-dir data_alt`。保存応答モードで起動する場合は `start.bat --offline` です。

## 管理者とパスワード

管理画面と管理APIは、公開・ローカルの両方でログインが必要です。管理者のユーザー名は1〜64文字（前後の空白不可）、パスワードは12〜256文字です。既定パスワードはありません。スコアサーバのアカウントとは別管理です。

ログインは8時間有効で、同じユーザーの最新5セッションまで保持します。終了時はサイドバーの「ログアウト」を押してください。期限切れ時は再ログインします。管理者情報とセッションは `data/admin_auth.sqlite3` に保存します。パスワードはハッシュで保存し、`config.json` に記載する必要はありません。配布ZIPには認証DBを含めません。

初期設定だけを行う場合は `start.bat init` を実行します。既に管理者がいれば変更しません。管理者の追加・パスワード再設定は `start.bat set-admin admin` で行い、`admin` を対象のユーザー名に置き換えます。パスワードはコンソールで確認入力し、そのユーザーの既存セッションを失効させます。独自の保存先では、通常起動と同じ `--data-dir` を指定してください。

管理者未作成で非対話起動した場合は起動を中止します。先にローカルのコンソールで `start.bat init` を実行してください。Viewer用中継API、公開Qualifier一覧とSID追加、Swagger、ガイドはログインなしで利用できます。

## 公開Qualifier一覧とSID追加

ログイン画面の「開催中のQualifierリーグ」から、ログイン不要の `/qualifiers/` を開けます。公開URLを設定した場合は、そのURLの `/qualifiers/` を共有してください。

実JBSL-WEBの開催中一覧にあり、中継サーバへ保存済みでQualifierが有効な実リーグだけを表示します。実一覧と保存設定の両方で開催中・受付中かつリーグ終了前であることが条件です。未取込・無効・停止・終了したリーグと同梱サンプルは表示しません。Qualifier開始前でも事前のSID追加ができます。

リーグごとの欄からSIDを1件ずつ追加できます。前後の空白を除いた1〜128文字で、途中の空白・改行・制御文字は不可です。先頭の0や大文字小文字を保持し、SIDの本人認証は行いません。同一接続元で1分10回まで受け付け、登録済みのSIDは二重登録しません。保存したSIDは中継APIへ反映され、再起動後も保持します。

公開画面ではSIDの追加だけができます。削除・置換やその他の設定変更は、管理者ログイン後に行ってください。ランキングに存在するSIDは、手動参加者から削除しても自動追加がONなら中継時に追加されます。

実中継モードでは開催中一覧を60秒間再利用します。取得に失敗した場合は前回情報と表示し、更新できるまでSID追加を停止します。保存応答モードでは保存済み一覧と取得日時を表示し、上流へ取得に行かずSID追加を検証できます。配布直後は実リーグが未取込のため、管理画面で一覧を取得し、対象リーグを取り込んでQualifierを有効にして保存してください。

公開一覧と専用APIは管理画面と同じ待受で提供します。後述のTunnel設定では、管理画面用ルートでそのまま転送できます。

## 接続とデバッグ

Viewerの `leaderboardApiUrl` に `http://127.0.0.1:18080/leaderboard/api/` を指定します。`activeLeagueApiUrl` と `playlistSongsApiUrl` は実JBSL-WEBを使用します。

管理画面で実リーグ一覧の取得、Qualifierの有効／無効・期間・参加者SID・譜面別回数上限の編集、障害・遅延の再現、中継ログの確認ができます。各項目の「?」と図付きガイドで操作を確認してください。実JBSL-WEBへの通信は公開APIのGETのみです。

未設定リーグは実JBSL-WEBのJSONをそのまま中継します（保存応答モードでも同様）。ランキングのSIDは中継のたびに参加者へ自動追加され、リーグ編集のチェックボックスでOFFにできます。既定はONです。日時の入力・一覧・ログはブラウザのローカル時刻です。

設定済みリーグの `participants` はSIDと `name` を返します。名前は `total_rank` を優先し、名前がないSIDはScoreSaberの `/api/v2/players/{SID}` から取得します。保存応答・プレビューも同じ規則です。取得成功は1時間再利用し、失敗後は60秒間再問い合わせせず、以前の名前またはSIDを返します。サンプルにSIDを追加した場合も名前取得が発生する場合があります。

実リーグの取込時と実中継モードで設定を開く際に、BeatSaverの公開APIから `metadata.duration` を取得して曲時間を自動入力します。保存で確定し、未設定分は実中継時にも補完します。取得失敗時は既存値（未設定なら空欄）を保持します。保存応答モードの編集・中継ではBeatSaverへ接続しません。

同梱の3023・3024・3025は架空のサンプルで、通信なしで利用できます。設定は初回起動時に `data/control.json` へ作成します。配布元の設定や取得済み実リーグは含まれていません。

スコアを提出する場合は別途スコアサーバを起動します。仮スコア管理の「リーグ取得先 URL」、または実スコア管理の `jbsl_web_url` を `http://127.0.0.1:18080` にしてください。この中継サーバは単独でも起動できます。

Swagger UIのJS/CSSとライセンスは `static/vendor/swagger-ui/` に同梱しています。初回セットアップ後、管理画面やSwaggerの表示に外部CDNは不要です。

## config.jsonで公開URLを設定する

このフォルダ直下の `config.json` は、配布時には `public_url` が空のローカル設定です。共有用に起動する場合は次の形式で公開URLを設定します。

```json
{
  "public_url": "https://jbsl-qualifier.rynan.com"
}
```

通常の `start.bat` で読み込みます。変更はサーバ再起動で反映します。設定ファイルの場所は作業ディレクトリや `--data-dir` に依存しません。公開時には管理画面のURL、Swaggerリンク、Viewer用接続設定を公開先へ揃え、画面・管理APIに内部URLや保存先の絶対パスを表示しません。

`public_url` が空文字、キーなし、またはファイルなしならローカル動作です。HTTPSのドメインを指定し、パス・ユーザー情報・クエリ・フラグメント・独自ポートは含めないでください。末尾の `/` と `:443` は省略形に正規化します。不正なJSONや設定では起動せずエラーになります。リーグ設定の `data/control.json` とは別のファイルです。

## Cloudflare Tunnelで共有する

`cloudflared` はこのサーバと同じPCで実行します。既定ポートの場合、公開ホストのAPI・Swaggerを `http://127.0.0.1:18080`、その他を `http://127.0.0.1:18764` へ転送します。ローカル管理のTunnelの `config.yml` では、Tunnel IDと認証ファイルを設定した上で次のルールを使います。

```yaml
ingress:
  - hostname: jbsl-qualifier.rynan.com
    path: '^/(leaderboard/api(/.*)?|docs/?|docs-assets(/.*)?|openapi[.]json/?|__mock__/state/?)$'
    service: http://127.0.0.1:18080
    originRequest:
      httpHostHeader: jbsl-qualifier.rynan.com
  - hostname: jbsl-qualifier.rynan.com
    service: http://127.0.0.1:18764
    originRequest:
      httpHostHeader: jbsl-qualifier.rynan.com
  - service: http_status:404
```

公開ホストとアプリの `public_url` を揃え、ポート変更時は転送先も変更してください。ダッシュボード管理でも、API用のパス指定を先に、パス指定なしの管理画面用ルートを後に設定します。Hostは公開ホスト名を渡し、localhostへ書き換えないでください。`/docs-assets/` と `/openapi.json` もAPI側へ転送します。[Cloudflare公式: Tunnelの設定](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/)、[HTTP Host Header](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/origin-parameters/#httphostheader)

設定後、公開URLの `/admin/` での保存、`/guide`、`/docs` のTry it outを確認します。`config.json` はDNSやTunnelを自動設定しません。

管理画面と `/admin/*` の管理APIはアプリ内ログインで保護します。追加でアクセスを制限したい場合はCloudflare Accessを併用できます。Viewer用APIへブラウザ向けの対話式ログインを適用すると取得できなくなるため、Accessの適用範囲を分けてください。[Cloudflare公式: Accessでアプリを公開する](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/)

公開時のViewer設定例では `allowDevelopmentHttp` は `false` です。HTTPのローカルスコアサーバを併用する場合は `true` に変更してください。

## Linux / systemd での起動・停止

Debian 12 / Python 3.13では、Windowsのbatを使わず、各アプリ専用の仮想環境を作ります。このアプリのフォルダで実行してください。uvは導入済みの前提です。

```bash
"$HOME/.local/bin/uv" venv --python 3.13 .venv
"$HOME/.local/bin/uv" pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python run.py init
.venv/bin/python run.py run
```

先にconfig.jsonの公開URL・接続先と管理者を設定してください。システムPythonの変更は不要です。2アプリの仮想環境は共有しません。

`deploy/systemd/jbsl-web-proxy.service` を同梱しています。UserとWorkingDirectory・ExecStartを実際の一般ユーザー・展開先に変更し、`/etc/systemd/system/` にコピーして登録します。実行ユーザーがuvのPython本体にもアクセスできることを確認してください。

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now jbsl-web-proxy
sudo systemctl status jbsl-web-proxy
sudo journalctl -u jbsl-web-proxy -n 100 --no-pager
sudo systemctl restart jbsl-web-proxy
```

両ポートの起動後に `ready` を出力します。Type=simpleのactive表示だけではアプリの準備完了を保証しないため、ログ・HTTP応答も確認します。SIGTERM・Ctrl+Cで両ポートを停止し、正常終了は0、起動失敗・想定外の待受終了・停止期限超過は非0終了です。異常終了は5秒後に再試行し、300秒内に5回の起動制限へ達すると停止します。原因修正後は `sudo systemctl reset-failed jbsl-web-proxy` と `sudo systemctl start jbsl-web-proxy` で再開します。手動stopでは自動再起動しません。

中継のHTTP終了猶予は既定90秒です。`run.py run --shutdown-timeout 120` のように5〜300秒で指定できます。`TimeoutStopSec` はこの値 + 60秒以上に合わせてください。 非同期の終了待ちにも上限を設けていますが、同期処理の停止を最終的に保証するのはsystemdのTimeoutStopSecです。停止期限内に完了しなかった要求の成功は保証しません。

LinuxではTIME_WAITが残っていても修正版同士の再起動が可能です。旧版はSO_REUSEADDRを使っていないため、旧版から初めて切り替える時だけ、停止後に約65秒待つ必要がある場合があります。同一ポートの二重起動は拒否します。同じdataを異なるポートで複数プロセスから操作しないでください。

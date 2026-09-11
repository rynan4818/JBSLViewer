# JBSL-WEB中継サーバ

`start.bat` を実行します。Python 3.11以上。初回はこのフォルダの `.venv` へ依存関係をインストールし、起動コンソールで管理者のユーザー名・パスワードを作成します。`config.json` の `public_url` を設定している場合、共有画面はそのURLの `/admin/` を使用します。空欄の場合は <http://127.0.0.1:18764/admin/>、Swaggerは <http://127.0.0.1:18080/docs> を開きます。管理画面とAPIはこのプロセスが提供します。

このフォルダだけで起動でき、スコアDBは作成しません。Ctrl+Cで中継APIと専用管理画面を終了します。

- `start.bat --offline`: 設定済みリーグは保存した応答を使用（未設定リーグの中継・一覧更新・新規取込は実APIへGET）。
- `start.bat --api-port 19080 --admin-port 19764 --data-dir data_alt`: ポートとデータ保存先を変更。
- `verify.bat`: 中継と管理画面のPython試験。

実リーグの取得、Qualifierのリーグ別編集、通信障害・遅延、プレビュー、API中継ログ、各項目の説明と図付きガイドに対応します。参加者追加用SIDは仮スコアの認証SIDとは独立しています。

- 未設定リーグはJBSL-WEBのJSON本文をそのまま中継します。設定済みリーグだけにQualifier設定を重ねます。
- リーグ編集の「元のランキングのSIDを参加者に自動追加」は既定ONです。総合順位と各譜面のスコアから、中継ごとにSIDを重複なく追加します。OFFなら手入力分だけを返します。既存設定に `auto_add_ranking_sids` がない場合もONとして動作します。
- 設定済みリーグの `participants` は `{"sid":"...","name":"..."}` を返します。名前は同じSIDの `total_rank[].name` を優先し、そこで取得できない場合は `https://scoresaber.com/api/v2/players/{SID}` の `name` を使います。保存応答モード・プレビューでも同じ規則です。ScoreSaberの取得成功は1時間再利用し、失敗後は60秒間再問い合わせしません。取得失敗時は以前の名前、なければSIDを返します。ScoreSaberへの同時問い合わせは最大4件、名前補完の待機上限は3秒です。数字以外を含むテスト用SIDはそのまま名前にします。
- 日時の入力・一覧・ログはブラウザのローカル時刻です。日本ならUTC+9で入力できます。保存・APIの日時はUTCです。
- 実リーグの取込時と実中継モードで設定を開く際に、BeatSaverの `/maps/hash/{hash}` の `metadata.duration`（秒）を自動入力します。保存で確定し、未設定分は実中継時にも補完します。同じhashの取得成功結果はプロセス内で再利用します。取得失敗時は既存値を保持し、未設定ならnullです。サンプルと保存応答モードの編集・中継ではBeatSaverへ接続しません。

`data/control.json` に設定と取込データを保存します。起動時の既定値は `config.py`、管理画面の保存値は `control.py` で検証します。公開中のAPI仕様は `/openapi.json`。実スコア管理と併用する場合は実スコア側の `jbsl_web_url` を `http://127.0.0.1:18080` に設定してください。

全体の接続・移行・自動検証は [../README.md](../README.md) を参照してください。

## 管理者ログイン

管理画面と `/admin/api/*` の管理操作には、公開・ローカルともにログインが必要です。初回起動時に作成したユーザー名とパスワードをログイン画面へ入力してください。ユーザー名は1〜64文字（前後の空白不可）、パスワードは12〜256文字です。コンソールでのパスワード入力は表示されず、確認入力が必要です。既定パスワードはありません。

管理者情報とセッションは `data/admin_auth.sqlite3` に保存し、スコアサーバの管理者とは別管理です。パスワードはソルト付きscryptハッシュ、セッションはトークンのハッシュで保存します。`config.json` にパスワードを記載する必要はありません。`--data-dir` を指定した場合は、そのフォルダの認証DBを使います。

ログインの有効期限は8時間で、再読込・サーバ再起動後も期限内のセッションを利用できます。同じユーザーのログインは最新5件まで保持します。終了時はサイドバーの「ログアウト」を押してください。期限切れ後は再ログインが必要です。

初期設定だけを行う場合、または管理者を追加・パスワードを再設定する場合は、サーバのフォルダで次を実行します。

```bat
start.bat init
start.bat set-admin admin
```

`init` は管理者が既に存在する場合は変更しません。`set-admin` の `admin` は対象のユーザー名に置き換えてください。新しいパスワードはコンソールで入力し、そのユーザーの既存セッションは失効します。独自の保存先を使っている場合は、通常起動と同じ `--data-dir` を指定してください。

管理者未作成の状態で非対話起動すると起動を中止します。先にローカルのコンソールで `start.bat init` を実行してください。初回管理者はWebから作成できません。

Viewerの `/leaderboard/api/*`、公開Qualifier一覧とSID追加、Swagger、ガイドはログインなしで利用できます。管理用Cookieは `/admin` に限定し、公開HTTPSではSecure属性を付けます。更新系管理APIにはセッションに加えてCSRFトークンが必要です。

## 公開Qualifier一覧とSID追加

ログイン画面の「開催中のQualifierリーグ」から、ログイン不要の `/qualifiers/` を開けます。公開URL設定時は [公開Qualifier一覧](https://jbsl-qualifier.rynan.com/qualifiers/) を共有してください。

一覧には、実JBSL-WEBの開催中一覧にあり、中継サーバへ保存済みでQualifierが有効な実リーグを表示します。実一覧と保存設定の両方で開催中・受付中かつリーグ終了前のものが対象です。未取込・Qualifier無効・停止・終了したリーグと同梱サンプルは表示しません。Qualifier開始前の事前登録も可能で、期間はブラウザのローカル時刻で表示します。

リーグごとの欄にSIDを入力し、「SIDを追加」を押してください。前後の空白を除いた1〜128文字を受け付け、途中の空白・改行・制御文字は使えません。先頭の0や大文字小文字を保持し、SIDの本人認証は行いません。追加は同一接続元で1分10回までです。

追加したSIDは手動参加者として保存され、中継APIに反映されます。再起動後も保持し、登録済みのSIDを再送しても二重登録しません。公開画面で可能なのは追加のみです。削除・参加者の置換・その他の設定変更は管理者ログイン後に行います。ランキングからのSID自動追加をONにしている場合、手動参加者から削除しても、ランキングに存在するSIDは中継時に引き続き自動追加されます。

実中継モードでは、開催中一覧の取得から60秒以内は保存情報を再利用します。更新に失敗すると前回情報であることを表示し、最新の開催状況を確認できるまでSID追加を停止します。保存応答モードでは上流へ取得に行かず、保存済み一覧と取得日時を表示してSID追加を検証できます。必要な実リーグの一覧取得・取込・保存は、先に管理画面から行ってください。

`/qualifiers/` と `/public/api/qualifier-leagues` は管理画面と同じ待受で提供します。以下のTunnel設定なら既存の管理画面用ルートで転送されるため、追加の振り分けは不要です。

## config.jsonで公開URLを設定する

このフォルダ直下の `config.json` に設定します。

```json
{
  "public_url": "https://jbsl-qualifier.rynan.com"
}
```

保存後に `start.bat` で起動します。起動済みの場合はCtrl+Cで停止して再起動してください。公開用の起動引数は不要です。設定は起動時に読み込み、作業ディレクトリや `--data-dir` に関係なくこのフォルダのファイルを使います。

公開時は、接続表示、Swaggerリンク、Viewerの `leaderboardApiUrl` が公開URLになり、管理APIの応答にも内部URLや保存先の絶対パスを含めません。ガイドや配信するHTML・JavaScriptにも内部IP・ポートを固定記載しません。サーバ内部のAPI確認は従来のループバック通信を使います。

`public_url` を `""` にする、キーを省略する、またはファイルを置かない場合はローカル動作です。URLはHTTPSのドメインだけを指定し、パス、ユーザー情報、クエリ、フラグメント、独自ポートは指定できません。末尾の `/` と標準ポート `:443` は省略形に揃えます。不正なJSONや設定は起動時にエラーになります。リーグ・挙動の保存先 `data/control.json` とは別の設定です。

## Cloudflare Tunnelの接続設定

`cloudflared` をこのサーバと同じPCで実行し、ホスト `jbsl-qualifier.rynan.com` をパス順で振り分けます。既定の待受は中継APIが `127.0.0.1:18080`、管理画面が `127.0.0.1:18764` です。ポートを変更している場合は転送先も揃えてください。

ローカル管理のTunnelでは、Tunnel ID・認証ファイルを設定した `config.yml` に次のルールを設定します。ダッシュボードで管理する場合も、同じ公開ホストのAPI用パスを先に、パス指定なしの管理画面用ルートを後に設定します。

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

パスは変更せず転送します。管理画面のルートだけを設定するとSwaggerと中継APIが404になるため、両方を設定してください。Hostをlocalhostへ上書きする設定は使用しません。アプリは設定済み公開ホストだけを追加で許可し、公開先のリダイレクトをHTTPSに揃えます。CloudflareからループバックへのHTTP転送でも、ブラウザのHTTPS Originで管理操作できます。[Cloudflare公式: パスによる振り分け](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/)、[HTTP Host Header](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/origin-parameters/#httphostheader)

設定確認には `cloudflared tunnel ingress validate` と `cloudflared tunnel ingress rule https://jbsl-qualifier.rynan.com/docs` を使えます。公開後に `/admin/` での保存、`/guide`、`/docs` のTry it outを確認してください。アプリの `config.json` を書くだけではDNSやTunnelは作成されません。

管理画面と管理APIはアプリの管理者ログインで保護します。追加でメンバーのアクセス元を制限したい場合は、Cloudflare Accessも併用できます。Accessを適用する範囲には `/admin/*` の管理APIも含めてください。ブラウザ以外のViewerからも `/leaderboard/api/*` に接続する場合は、対話式ログインを要求するAccessポリシーの適用範囲を分ける必要があります。[Cloudflare公式: Accessでアプリを公開する](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/)

公開時のViewer設定例では `allowDevelopmentHttp` は `false` です。HTTPのローカルスコアサーバを併用するときは、その接続に合わせて `true` にしてください。

## 配布用ZIPの作成

`make_zip.bat` をダブルクリックするか、このフォルダで実行します。`dist/` に日時と識別子付きのZIPを新しく作成し、収録した全ファイルのSHA-256を検証します。既存のZIPは上書きしません。ZIP作成にはWindows標準のPowerShell/.NETだけを使います。

```bat
make_zip.bat
make_zip.bat -OutputDirectory "C:\temp\JBSL 配布"
```

現在の設定・DB・リプレイ・ログ・仮想環境・テスト・過去のZIPは含めません。配布先はZIPをフォルダごと展開し、同梱の `README.md` に従って `start.bat` を実行します。初回の依存パッケージ導入にはPythonとネット接続が必要です。

公開URLの運用設定も収録しません。`config.example.json` をZIP内の `config.json` として収録し、配布先は `public_url` が空のローカル設定で起動します。

収録対象は [package-files.json](package-files.json) の明示的な一覧です。実行に必要なファイルを追加・改名した場合は、この一覧も更新してください。一覧外のファイルは、任意の名前で保存したデータも含めて収録しません。必要なファイルが欠けていれば作成を中止します。配布用READMEの原稿は [DISTRIBUTION.md](DISTRIBUTION.md) です。検証用コードとZIP作成ツール自体は、導入用ZIPには含めません。

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

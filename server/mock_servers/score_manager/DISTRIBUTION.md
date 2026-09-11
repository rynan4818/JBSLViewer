# デバッグ用仮スコア管理サーバ（配布版）

JBSLViewer用のローカルデバッグサーバです。Python 3.11以上とWindowsを使用します。ゲームDLLは不要です。

## 初回起動

1. ZIPを展開し、`score_manager` フォルダ全体を任意の場所へ置きます。
2. Python 3.11以上をインストールします。
3. `start.bat` を実行します。初回は `.venv` を作成し、必要パッケージを取得します。初回だけインターネット接続が必要です。
4. **http://127.0.0.1:18765/admin/** を開きます。管理画面のログインは不要です。

APIは `http://127.0.0.1:18082`、Swagger UIは `http://127.0.0.1:18082/docs` です。Ctrl+CでこのAPIと専用管理画面を終了します。

Pythonの場所を指定する場合はPowerShellで実行します。

```powershell
$env:JBSL_PYTHON = 'C:\Path\To\Python\python.exe'
.\start.bat
```

別ポート・保存先を使う場合は `start.bat --api-port 19082 --admin-port 19765 --data-dir data_alt` です。

## Viewer・リーグ取得先の設定

Viewerには次の設定を使用します。

```json
{
  "scoreServerBaseUrl": "http://127.0.0.1:18082",
  "allowDevelopmentHttp": true
}
```

管理画面の「リーグ取得先 URL」の既定値は `http://127.0.0.1:18080` です。別途配布するJBSL-WEB中継サーバを起動し、必要に応じて取得先を変更してください。取得先が停止中でも管理画面と保存済みデータの閲覧は動作します。

通常起動ではテスト用SIDで認証します。そのSIDを中継側のリーグ参加者にも設定します。テストSIDを変更したときは、この管理画面でViewerセッションを失効して再認証してください。

## 保存内容と確認画面

初回起動時に `data/control.json`、`data/score.sqlite3`、`data/replays/` を作成します。配布元の設定・ユーザー・提出・リプレイは同梱していません。

「提出スコア」「Challenge」「消費回数」「受付履歴」で提出内容と状態を確認します。「サーバ挙動」で障害・遅延、時計差、受付期限、キャッシュ、提出サイズ上限などを設定できます。各項目の「?」と図付きガイドを参照してください。

この仮サーバはローカルのデバッグ用です。BSOR検証は基本識別情報までで、点数の完全再計算は行いません。Swagger UIのJS/CSSとライセンスは `static/vendor/swagger-ui/` に同梱しています。

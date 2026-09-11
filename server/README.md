# Qualifier用サーバー

Qualifierブランチで使用する3つのサーバーの公開用ソースです。

| フォルダー | 役割 | API / 管理画面の既定ポート |
|---|---|---|
| [score_server](score_server/README.md) | 実スコア管理。認証、予約、結果・Replay保存、回数管理 | 18081 / 18763 |
| [mock_servers/jbsl_web_proxy](mock_servers/jbsl_web_proxy/README.md) | JBSL-WEB中継とQualifierリーグ設定 | 18080 / 18764 |
| [mock_servers/score_manager](mock_servers/score_manager/README.md) | テスト用の仮スコア管理。障害や期限などの再現 | 18082 / 18765 |

実スコア管理はPython 3.12以上、中継と仮スコア管理はPython 3.11以上を使用します。起動・初期設定は各フォルダーの `start.bat` とREADMEを参照してください。各アプリは自分の `.venv` を使用します。

## 設定とデータ

`config.example.json` は秘密値を含まない設定例です。起動時に作成される、またはローカルで作成する `config.json` に接続先・Steam APIキーなどを設定します。初回管理者の設定方法は各READMEに記載しています。

実設定・APIキー・DB・提出済みReplay・認証情報・ログ・バックアップは公開対象外です。これらを `server` のソースと一緒にGitへ追加しないでください。共通の [.gitignore](.gitignore) で既定の保存先を除外しています。独自の保存先を指定する場合はリポジトリ外を使用してください。

同梱fixtureは架空のテスト用データです。実運用の参加者一覧やスコア履歴は含みません。Swagger UIのvendor資産に付属するLICENSE・NOTICEも保持してください。

## テスト

各フォルダーの `verify.bat` が入口です。実スコア管理の一括検証には.NET 8をターゲットにできるSDKと.NET 8ランタイム、ブラウザー検証用の環境も必要です。`score_server/validation/ViewerContract.csproj` は、このリポジトリの同じQualifierブランチにあるゲーム外C#テストを参照します。

Pythonテストだけを実行する場合は、実スコア管理のフォルダーで `.venv\Scripts\python.exe -m pytest -q` を実行します。中継と仮スコア管理の検証方法は [mock_servers/README.md](mock_servers/README.md) を参照してください。テストは一時データを使用し、運用中の設定やDBを渡さないでください。

## 配布ZIP

配布したいサーバーのフォルダーで `make_zip.bat` を実行します。`dist/` に新しいZIPができ、ファイルごとのSHA-256が検証されます。

`make_zip.bat`、`package.ps1`、`package-files.json` は一組です。配布対象は `package-files.json` に列挙されたファイルだけです。実設定・DB・ログ・仮想環境は入力に含めず、設定が必要な場合は設定例から作成します。配布一覧を変更する場合も、実設定を追加しないでください。

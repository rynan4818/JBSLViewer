# JBSL-WEB中継と仮スコア管理

[サーバー全体の案内](../README.md)と、各アプリのREADMEを参照してください。

- [jbsl_web_proxy](jbsl_web_proxy/README.md): JBSL-WEBからリーグを取得し、Qualifierの設定を重ねてViewerとスコア管理へ返します。`jbsl_web_proxy/start.bat` で起動します。
- [score_manager](score_manager/README.md): テスト用の認証・予約・スコア提出を処理し、障害・遅延・期限などを再現します。`score_manager/start.bat` で起動します。

仮スコア管理の既定の上流は中継の `http://127.0.0.1:18080` です。実スコア管理と併用するときは、`../score_server` 側の `jbsl_web_url` を中継のURLへ設定します。実スコアと仮スコアは別ポート・別データを使用します。

## 検証

各フォルダーの `verify.bat` は、仮想環境を用意してそのアプリのPythonテストを実行します。コマンドで実行する場合は、`server` フォルダーを作業ディレクトリにします。

```bat
mock_servers\jbsl_web_proxy\.venv\Scripts\python.exe -m pytest mock_servers\jbsl_web_proxy\tests -q
mock_servers\score_manager\.venv\Scripts\python.exe -m pytest mock_servers\score_manager\tests -q
```

テストで使用する `fixtures` は架空の契約確認用データです。運用中の `data`・`config.json` をテストに渡す必要はありません。APIや管理画面の詳細は各アプリ同梱のSwaggerとガイドを参照してください。

## 配布

それぞれのフォルダーの `make_zip.bat` で、必要なファイルを含む配布ZIPを作成できます。`dist` と運用データはGitへの追加対象外です。実設定や秘密値を配布一覧へ追加しないでください。

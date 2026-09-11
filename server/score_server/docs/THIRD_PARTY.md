# 同梱するAPIドキュメントの資産

Swagger UIは管理用ポートでローカル配信します。サーバ起動や画面表示のたびに取得する仕組みはありません。

| 項目 | 内容 |
|---|---|
| パッケージ | `swagger-ui-dist` **5.32.15** |
| 配布元 | [Swagger公式パッケージ](https://www.npmjs.com/package/swagger-ui-dist/v/5.32.15) |
| ソース | [swagger-api/swagger-ui](https://github.com/swagger-api/swagger-ui) |
| 保存先 | `jbsl_score/static/vendor/swagger-ui/` |
| 本体ライセンス | Apache-2.0。同梱の `LICENSE`、`NOTICE` を参照 |
| バンドル内の表示 | `swagger-ui-bundle.js.LICENSE.txt` を同梱 |
| 整合性 | 配布アーカイブのSHA-512を検証。各保存ファイルのSHA-256を `manifest.json` に記録 |

開発時の再取得は `.venv\Scripts\python.exe scripts\vendor_swagger.py`。バージョン更新時はスクリプト内の固定バージョンと、公式registryで確認したintegrityを更新してから取得し、ライセンス・ブラウザ検証を再確認します。アーカイブを一括展開せず、名前を指定した通常ファイルだけを保存します。

表示設定は [Swagger UIの公式設定仕様](https://swagger.io/docs/open-source-tools/swagger-ui/usage/configuration/) を参照し、`supportedSubmitMethods=[]`、`validatorUrl=null`、`persistAuthorization=false` としています。静的資産の配信は [FastAPIの自己ホスティング手順](https://fastapi.tiangolo.com/how-to/custom-docs-ui-assets/) に沿い、初期化スクリプトも独立したローカルファイルに置いています。既存の `script-src 'self'` と `style-src 'self'` を維持します。SwaggerのHTMLだけは、同梱CSSのアイコンを表示するため `img-src 'self' data:` を指定します。管理画面・ガイド・APIへの制限は変更しません。

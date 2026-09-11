# チャレンジ専用画面のバージョン別移植（2026-09-11）

取り込み元: BS1.29.1 `addb99d63f18de7c9ff665b7ecc04ca5c9ab26f8`（チャレンジ専用画面とTA方式の直接プレイ開始に対応）。各対象ブランチの既存API対応に、このコミットの機能を移植した。

リーグ一覧・譜面一覧・曲詳細、参加対象外のダイアログ、CHALLENGE / PRACTICEの直接開始、専用リザルトからの復帰、既存の右側リーダーボード、10件のページ送り、譜面一覧でのTOTALを含む。PRACTICEは曲頭からの通常プレイで、予約・回数消費・チャレンジ結果送信を行わない。

## TournamentAssistantとの照合

[配布ページ](https://download.tournamentassistant.net/)と公開リポジトリのブランチ先端を確認した。下記のコミットと各版の `SongUtils.cs`、`QualifierCoordinator.cs`、`SongDetail.cs` を照合した。

| JBSL対象 | TAの対応コミット | 確認したTAブランチ先端 |
|---|---|---|
| 1.37.1 | [b7799d5: 1.37.0対応](https://github.com/MatrikMoon/TournamentAssistant/commit/b7799d5ab31f182f0a7c78c1ff955dfedbf365a5) | `ssl-tauri-discord-1.37.0` / `f50bbe1afb0ad8dc5240574d9f650d7e51249917` |
| 1.39.1 | [4cb9752: BeatmapKeyへの移行](https://github.com/MatrikMoon/TournamentAssistant/commit/4cb97526b0a21117bd9bbdde2ea2824eb756b9e5) | `ssl-tauri-discord-1.39.1` / `df540291cc65a57db4eccf77aa4449449a37ffa4` |
| 1.40.8 | [d52c64d: 1.40.8対応](https://github.com/MatrikMoon/TournamentAssistant/commit/d52c64d00ad7c84e073fe5c306928b5892cd47db)、[91fa59d: ライト色修正](https://github.com/MatrikMoon/TournamentAssistant/commit/91fa59d90797b4045d5799b9e97eab7773bc6dc9) | `ssl-tauri-discord-1.40.8` / `668b235b389765dcf9f5cdd50cab27d6171063d4` |
| 1.42.0 | [2c9b515: 開始API対応](https://github.com/MatrikMoon/TournamentAssistant/commit/2c9b5156b4d4d46cc0dbd9c261c379b813ea92d4) | `ssl-tauri-discord-1.42.0` / `cfacb28cff9af5170146c6516fba4877a96c8f11` |

TAの1.37系ブランチは1.37.0向けであり、JBSLの1.37.1については1.37.1本体のDLL・ソースで個別に確認した。TA側の現行一括ビルド設定では1.37.0はコメントアウトされている。

1.40.8以降は `ShouldOverrideLightshowColors() || colors != null` を渡し、明示的な色指定をライトにも適用するTAの修正を反映した。1.42.0では `GameplayAdditionalInformation(Localization.Get("BUTTON_MENU"))` と新版のコールバックを使用する。

TAと同じく `MenuTransitionsHelper.StartStandardLevel` を呼び、ソロの選曲画面を開かず、専用フローを保持する。指定難易度を確認した `BeatmapKey` と `BeatmapLevel` を渡す。1.37.1～1.40.8はロード済みの `IBeatmapLevelData` も渡すが、1.42.0はTAと同じくオプションの `beatmapLevelData` に `null` を渡し、本体の `BeatmapLevelsModel` に読み込みを任せる。JBSLの参加資格・予約・提出処理は既存の担当クラスが処理する。譜面側の色指定も、1.37.1～1.40.8では本体APIへ渡し、1.42.0では本体が渡された `BeatmapLevel` から解決する。

TA由来の各コード・BSMLの先頭に元ファイル、リビジョン、[指定URL](https://github.com/MatrikMoon/TournamentAssistant?tab=MIT-1-ov-file)とMIT全文を記載した。`THIRD-PARTY-NOTICES.txt`にはTA、BeatLeader、JBSLViewerのライセンス全文を収録した。

## ゲームAPIの調整

提供された `D:\PROGRAM\github\@Maintenance\CameraSongScript\BeatSaber\SourceCode` の各版ソースと、インストール済みの実DLLを照合した。

- 新しい譜面モデルを `QualifierBeatmap` にまとめ、Characteristic・難易度の一致、ロード完了、選択世代を確認する。カスタム譜面のノーツ数等は `BeatmapDataLoader.LoadBasicBeatmapDataAsync` で取得する。読み込めなかった譜面は開始できない。
- 1.37.1には `ContainsBeatmapData` がないため、指定キーに対するネイティブローダーの正常終了を確認する。ジャケットのキャンセルトークンとBSML 1.11系の小文字プロパティを使用する。
- 1.39.1以降はBSMLの `TableView` / `MenuButtons.Instance`、別アセンブリへ移動したUI部品へ対応する。
- 1.40.8以降はノーツ速度計算の追加引数、1.42.0では `GetBeatmapLevel` の大文字小文字照合と17引数の開始APIへ対応する。
- リザルトは `Init` の6引数版で初期化する。専用インスタンスのイベント登録・解除、CONTINUE、PRACTICEのRESTART、Quit、二重通知と遅延通知への対処を保持する。

## 初回移植時の検証結果

| 対象 | BeatSaberVersion.txt | ゲーム外テスト | 実DLLのAPI照合 | BSML・画面接続・ライセンス |
|---|---|---:|---:|---:|
| 1.37.1 | 1.37.1_9767668645 | 299 | 491 | 475 |
| 1.39.1 | 1.39.1_1715 | 300 | 492 | 475 |
| 1.40.8 | 1.40.8_7379 | 304 | 493 | 475 |
| 1.42.0 | 1.42.0_12297 | 304 | 498 | 475 |

すべてReleaseビルドに成功した。テストは直接開始・準備中断・PRACTICE非消費・結果復帰・二重通知防止・10件ページ送り・TOTAL・参加条件等を検証する。API検証は型・メンバー・Harmony引数・参照元を、画面検証は実BSMLの属性と埋め込みリソース、ネイティブの開始・リザルト接続、MIT表記を確認する。

今回の検証対象は表の4版で、VR内での画面操作・実プレイは未実施。以前の版範囲全体について今回の新機能を検証したものではない。

ゲーム参照はそれぞれ `C:\Program Files (x86)\Steam\steamapps\common\Beat Saber_<対象版>` を使用した。Mod参照のみ、1.39.1は `Beat Saber_1.39.1SS`、1.42.0は `Beat Saber_1.42.3` を使用する。1.39.1通常フォルダーにはLeaderboardCore.dll、1.42.0にはBS_Utils.dllがないため、既存ビルド設定と同じ分離を維持した。

再現手順は各版の `build.ps1`（Releaseビルド、ゲーム外テスト、API検証）と、`JBSLViewer.Qualifier.Tests/verify_ui.ps1 -GameDirectory <対象ゲーム> -ModReferencesDir <Mod参照元>`。ビルドではゲームへのコピーを無効にした。

初回の4版統合ZIPは計5ファイル。その後、動作確認済みの1.29.1も同梱した5版統合ZIPを作成した。5版統合ZIPはルートの `THIRD-PARTY-NOTICES.txt` と、1.29.1 / 1.37.1 / 1.39.1 / 1.40.8 / 1.42.0の各 `BS<対象版>/Plugins/JBSLViewer.DLL` の計6ファイルのみ。検証資料・README・単独LICENSE・PDB・依存DLLは統合ZIPへ含めない。

## BS1.42.0の開始時例外の修正（2026-09-11）

1.42.0では、CHALLENGEの予約成功後とPRACTICEの開始時に `standard_play_invocation_failed` が発生した。ログの `ArgumentException` と本体ソースから、`MenuTransitionsHelper` が内部の `BeatmapLevelsModel` と渡された `beatmapLevelData` を同時にシーン初期化へ渡し、`GameplayCoreSceneSetupData` が拒否していることを確認した。初回のAPIシグネチャ照合とゲーム代替は、この引数の組み合わせを検証できていなかった。

`QualifierDirectPlayController.StartAsync` の共通開始経路で `beatmapLevelData` を `null` に変更した。TAの1.42.0対応ブランチと同じ方法で、指定したKey / Levelを本体に読み込ませる。選曲時の `QualifierBeatmap.Data` / `BasicInfo` は保持し、指定難易度の事前読み込みと開始可否確認に引き続き使用する。

ゲーム代替に本体の拒否条件を追加すると、修正前のコードで開始テストが失敗することを確認した。修正後はCHALLENGEとPRACTICEの両方で「事前読み込み済みの同じKey / Levelを渡し、開始APIのDataはnull」を検証する。`verify_ui.ps1` は実DLLのモデル引数と例外を確認し、ビルドした呼び出し命令がnullデータを渡すことも検証する。

修正版は、1.42.0へ切り替え済みの `C:\Program Files (x86)\Steam\steamapps\common\Beat Saber` をゲーム本体・Mod双方の参照元としてReleaseビルドした。ゲーム外テスト307件、実DLLのAPI照合498件、画面接続・開始引数・ライセンス検証478件が成功した。追加したDLL検証が旧DLLのデータ引数を拒否することも確認済み。

5版統合ZIPでは1.42.0のDLLを更新し、ほか4版とライセンス通知は配布済みの内容を保持する。修正版DLLのSHA-256は `2C06385BBE8DBC47F132C8441942EAE167223F3B6CCC87307270C02829E44DEE`。VR実機での操作・実プレイ確認は未実施。

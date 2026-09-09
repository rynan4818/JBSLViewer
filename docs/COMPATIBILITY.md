# BS1.40.8: Qualifier port

基準版: Beat Saber 1.40.8。実DLL照合範囲: 1.40.0～1.40.8。Mod: 0.4.0。移植元はBS1.29.1の `9c3fc19`、土台はmainの `d040b59`。各ブランチにQualifierのソースを取り込み、版をまたぐ実行時分岐や共通DLLを追加していない。

## このブランチのAPI

- 譜面は `BeatmapKey` / `BeatmapLevel`。ノーツ追加は `(NoteData, NoteSpawnData)` の2引数で、独立した `NoteSpawnData` を使用。
- `GameplayCoreInstaller` が登録する `VariableMovementDataProvider` を直接注入し、録画開始時とspawn初期化時のjumpDistanceを取得。環境は `targetEnvironmentInfo`。
- 認証は `IPlatformUserModel.GetUserInfo(CancellationToken)` と本体の `PlatformAuthenticationTokenProvider`。
- BSMLは1.12系のプロパティ名を使用。シーン遷移イベントは `SceneTransitionType` を含む形式。
- 1.40.8の `NoteData.ScoringType` はArc/Chainへ名称が変わり、ArcHeadArcTail=6、ChainHeadArcTail=7、ChainLinkArcHead=8が追加されている。録画はBeatLeaderと同じ整数式 `((int)scoringType + 2) * 10000 + ...` を維持し、新しいIDもInt32でBSORへ保存する。名前による分岐や旧スコア表への変換は行わない。最大スコアは本体の `ScoreModel` と `GameplayModifiersModelSO` で算出。
- FPSは `Time.timeScale / Time.deltaTime`。予約と開始前失敗結果には予約時の実ゲーム版、Clear/FailとBSORには同じ実ゲーム版を保持。

## 検証結果（2026-09-10）

`C:\Program Files (x86)\Steam\steamapps\common\Beat Saber_1.40.8` の実DLLでReleaseビルド成功。参照Mod: BSIPA 4.3.6、BSML 1.12.5、SiraUtil 3.2.1、BS Utils 1.14.2、LeaderboardCore 1.7.0。

- C#テスト154項目成功: 認証、予約の一回性、終了理由、Outbox、再送信、ランキングキャッシュ、JSON/BSOR、ゲーム版の保持。
- API照合399項目成功。1.40.0、1.40.1、1.40.2、1.40.3、1.40.4、1.40.5、1.40.6、1.40.7、1.40.8の各本体DLLでも同じDLLを照合。Mod参照は1.40.8のセットで固定した。各本体でのMod導入・実機動作確認とは区別する。
- 仮サーバHTTP試験17項目成功: 認証・予約・開始・結果と合成BSOR、同一キー100並列予約と重複結果の一貫性。

1.40.8本体ソースでPlay、結果Finish、スコア処理順序、Modifier最大スコア、Swing、Pause/Restart UI、DI登録とイベント解除を確認。他の1.40.0～1.40.7は実DLLで利用APIを確認。ゲーム内UI、Zenject実行順、Steam/Oculus実認証、VR実プレイと録画品質は未確認。1.40.9以降は今回の範囲外。

## BeatLeader履歴

`Source/manifest.json` の `22173627`（1.39.0→1.40.0）、実装の `d49f641d`（独立NoteSpawnDataとVariableMovementDataProvider）、`fbf1a1ff`（Compile 1.40.8+とFPS補正）を参照。録画のnoteID式・イベント・距離取得を本体APIと照合した。ライセンスは同梱の第三者表示を参照。

## 成果物と実機確認

`build.ps1` が `artifacts/BS1.40.8/<日時>/` にZIP、DLL、ライセンス、ビルドログ、API照合、self-testログ、SHA256を出力する。ゲームへのコピーは行わない。

対応Modとテスト用リーグを用意し、Challenge予約→通常Play→Clear/Fail/Quit、Pause/Restart抑止、送信禁止、認証とOutbox再送信を実機で確認する。Arc/Chain複合ノーツを含む譜面のBSORも確認対象。

BeatSaberVersion.txtがない1.40.5、1.40.6、1.40.7はglobalgamemanagers内のPlayerSettingsから、それぞれ1.40.5_5928、1.40.6_6407、1.40.7_7060の文字列を確認した。API照合では各ゲームDLLの実ファイルが対象フォルダーから解決されることも確認する。

# BS1.39.1: Qualifier port

基準版: Beat Saber 1.39.1。Mod: 0.4.0。移植元: BS1.29.1 の `9c3fc19435e03a1fcafe727260e90e75da0204ac`。移植先の土台: main の `d040b594807584797a20e9220b0500a20ec2bb03`。

## 専用実装

- 譜面の識別と曲情報は `BeatmapKey` / `BeatmapLevel` を使用。
- `noteWasAddedEvent` は `(NoteData, BeatmapObjectSpawnMovementData.NoteSpawnData)` の2引数。ジャンプ距離は `BeatmapObjectSpawnController.jumpDistance`、環境は `GameplayCoreSceneSetupData.targetEnvironmentInfo`。
- ユーザー情報は `IPlatformUserModel.GetUserInfo(CancellationToken)`。Steam ticketとOculusのXPlatform tokenは本体の `PlatformAuthenticationTokenProvider` から取得。
- シーン遷移イベントは `SceneTransitionType` を含む引数へ変更。Modifier変更はメニューのTickと開始直前の再確認で検出。
- BSMLは1.12系のプロパティ名を使用。ゲーム参照とMod参照を分離し、ローカルの古い `ReferencePath` より指定したDLLを優先。
- 予約時の実ゲーム版を保持し、開始前失敗結果にも渡す。Clear/Fail結果はBSORと同じ `Application.version` を維持。FPSは `Time.timeScale / Time.deltaTime`。

## 参照と確認結果

`C:\Program Files (x86)\Steam\steamapps\common\Beat Saber_1.39.1SS` の実DLLでReleaseビルドを実施。BSML 1.12.4、SiraUtil 3.1.14、BS Utils 1.14.2、LeaderboardCore 1.7.0を使用。

- C#テスト: 154項目。予約の一回性、認証世代、タイムアウト、Outbox永続化、送信再試行、JSONとBSOR、実ゲーム版の保持を検証。
- API照合: 399項目。コンパイル済みModのゲーム/Modメンバー、Harmonyの対象と引数名、反射で読むprivateフィールド、manifestを実DLLと照合。
- ローカルHTTP試験: 17項目。認証・予約・開始・結果・BSOR送信、同一キー100並列予約を検証。録画データは通信試験用の合成データ。

ゲーム内でのUI・Zenjectの実行順・Steam/Oculusの実認証・実プレイの録画品質は未確認。コンパイルと静的照合の成功だけで実機動作を保証しない。

## 本体ソースとBeatLeader履歴

本体ソース: `CameraSongScript/BeatSaber/SourceCode/1.39.1` の `GameplayCoreSceneSetupData`、`BeatmapObjectManager`、`ScoreController`、`GameplayModifiersModelSO`、`SaberMovementData`、`SaberSwingRatingCounter`、`PlatformAuthenticationTokenProvider` とメニュー/結果遷移を確認。

BeatLeaderの `Source/manifest.json` のgameVersion変更と周辺実装を調査した。`6f2d8f2e` / `3d92b690` の1.39対応（rotation引数削除）、`70c4a02d` / `ecc7c732` の1.29.1へ戻した差分を逆方向の移植に参照。`fbf1a1ff` のFPS補正も反映した。ライセンスは同梱の第三者表示を参照。

1.38.0ではノーツイベントが3引数のため、このDLLの対象に含めない。1.37.1系・1.40.8系・1.42.0系は別ブランチとする。

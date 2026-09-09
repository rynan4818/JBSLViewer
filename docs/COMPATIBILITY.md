# BS1.42.0: Qualifier port

基準版: Beat Saber 1.42.0。対象: 1.42.0～1.44.1。Mod: 0.4.0。移植元はBS1.29.1の `9c3fc19`、土台はmainの `d040b59`。各ブランチにQualifierのソースを取り込み、版をまたぐ実行時分岐や共通DLLを追加していない。

## このブランチのAPI

- 旧 `IPlatformUserModel` は使わず、`OculusStudios.Platform.Core.IPlatform` を直接注入する。`vendor` のValve/MetaをSteam/Oculusへ対応させ、`user.userId` と `user.displayName` を読む。userId=0と未対応vendorは挑戦用の認証対象にしない。
- 本体の `PlatformAuthenticationTokenProvider(IPlatform, UserInfo)` からSteam ticket / Oculus XPlatform tokenを取得。旧APIへ戻す互換処理は追加しない。キャンセル前後を確認し、ticketをOutboxへ保存しない。
- 譜面は `BeatmapKey` / `BeatmapLevel`。ノーツ追加は `(NoteData, NoteSpawnData)`。`VariableMovementDataProvider.jumpDistance` と `targetEnvironmentInfo` を直接使用する。
- `IReturnToMenuController` は `BeatSaber.Destinations.dll`、認証トークンは `BeatSaber.Multiplayer.Core.dll` に移動しているため参照を追加。
- スコア処理順とSwingで使うprivateフィールドを本体ソースと実DLLで確認。Arc/Chainの追加種別は本体の整数値をnoteIDへ記録し、BSORはInt32を維持。最大スコアは本体APIで算出。
- FPSは `Time.timeScale / Time.deltaTime`。予約と開始前失敗結果にも実ゲーム版を保持し、Clear/FailとBSORのgameVersionを一致させる。

## 参照環境と検証結果（2026-09-10）

基準の本体は `C:\Program Files (x86)\Steam\steamapps\common\Beat Saber_1.42.0`。不足するMod参照は1.42.3のフォルダーから読み取る。参照Mod: BSIPA 4.3.7、BSML 1.14.1、SiraUtil 3.3.1、BS Utils 1.14.3、LeaderboardCore 1.7.0。DLLをゲーム側へコピーして補う方式にはしていない。

- 1.42.0の本体と上記Mod参照でReleaseビルド成功。
- C#テスト154項目成功: 認証、予約の一回性、終了理由、Outbox、再送信、ランキングキャッシュ、JSON/BSOR、実ゲーム版の保持。
- API照合403項目成功。1.42.0、1.42.2、1.42.3、1.43.0、1.44.0、1.44.1の本体DLLで同じDLLを照合した。1.43.0ではそのフォルダーのSiraUtil 3.4.0を含むModセットも使用し、他は1.42.3のMod参照を使用。
- 仮サーバHTTP試験17項目成功: 認証・予約・開始・結果と合成BSOR、同一キー100並列予約と重複結果の一貫性。

1.42.0、1.42.2、1.42.3、1.43.0、1.44.1の本体ソースを参照。1.44.0は実DLLで確認。確認対象はメニューPlay/Practice、結果Finish、スコア処理順、Modifier最大スコア、Swing、Pause/Restart UI、DI登録、イベント解除、認証API。1.42.1の資料は手元になく、1.44.2以降は今回の範囲外。

1.42.0ではBS UtilsとLeaderboardCore、1.44.0/1.44.1では今回使うMod群が未配置のため、これらのゲームをそのまま起動した状態での確認はしていない。ゲーム内UI、Zenject実行順、Steam/Oculus実認証、VR実プレイと録画品質は未確認。

## BeatLeader履歴

`Source/manifest.json` の `c0f05bab`（1.40.9→1.42.0）と実装の `8bc07888` を参照。新しい認証APIと戻り先インターフェースのDLL移動は本体ソースと実DLLを根拠に実装した。録画は `d49f641d`、FPSは `fbf1a1ff` の変更も参照。ライセンスは同梱の第三者表示を参照。

## 成果物と実機確認

`build.ps1` が `artifacts/BS1.42.0/<日時>/` にZIP、DLL、ライセンス、ビルドログ、API照合、self-testログ、SHA256を出力する。ゲームへのコピーは行わない。

各本体へ対応Modを導入し、テスト用リーグで実認証、Challenge予約→通常Play→Clear/Fail/Quit、Pause/Restart抑止、送信禁止、Outbox再送信、Arc/Chainを含むBSORの実機確認を行う。

結果画面の補足表示にはBSML 1.14系のCreateCurvedUITextとTMPのtextWrappingModeを使用。API照合は各ゲームDLLが対象フォルダーから解決されることも確認し、Mod参照フォルダーの本体DLLへの置き換わりを拒否する。

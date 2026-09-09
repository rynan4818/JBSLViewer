# BS1.37.1: Qualifier port

基準版: Beat Saber 1.37.1。対象: 1.37.1～1.37.2。Mod: 0.4.0。移植元はBS1.29.1の `9c3fc19`、土台はmainの `d040b59`。Qualifierは各ブランチ内へソースとして取り込み、版をまたぐ実行時分岐や共通DLLを追加していない。

## このブランチのAPI

- 譜面は `BeatmapKey` / `BeatmapLevel`、難易度変更イベントはViewControllerの1引数。
- ノーツ追加イベントは `(NoteData, BeatmapObjectSpawnMovementData.NoteSpawnData, float)` の3引数。距離は `_spawn.jumpDistance`、環境は `_setup.environmentInfo`。
- シーン遷移開始は `Action<float>`、完了は `Action<ScenesTransitionSetupDataSO, DiContainer>`。1.37.4の `SceneTransitionType` を含む形式とは異なる。
- 認証は `IPlatformUserModel.GetUserInfo(CancellationToken)` と本体の `PlatformAuthenticationTokenProvider`。
- BSMLは `background` / `tableView` / `values` / `interactable` / `BSMLSettings.instance` を使用。旧フィールドがなくなる1.12系を避けるためmanifestを `>=1.11.4 <1.12.0` とした。インストール済みSemVerパーサーで1.11.4の許可と1.12.0の拒否を確認。
- 予約に実ゲーム版を渡し、開始前失敗結果も予約時の版を保持する。Clear/FailとBSORは同じ実ゲーム版を保持。

## 検証結果（2026-09-10）

`C:\Program Files (x86)\Steam\steamapps\common\Beat Saber_1.37.1` の実DLLでReleaseビルド成功。参照Mod: BSIPA 4.3.6、BSML 1.11.4、SiraUtil 3.1.11、BS Utils 1.14.0、LeaderboardCore 1.6.0。

- C#テスト154項目成功: 認証、予約の一回性、各終了理由、タイムアウト、Outbox永続化・再送信、ランキングキャッシュ、JSON/BSOR、実ゲーム版の保持。
- API照合399項目成功: コンパイル済みModの直接参照、Harmonyの対象と引数名、反射対象privateフィールド、manifest。1.37.2の本体・Mod DLLでも同じDLLの照合に成功。
- 仮サーバHTTP試験17項目成功: 認証、予約、開始、Clear/Failと合成BSOR送信、同一キー100並列予約と重複結果の一貫性。

1.37.1の本体ソースでPlay、結果Finish、スコア処理順序、Modifierによる最大スコア、Swing、Pause/Restart UI、イベント購読解除を確認した。1.37.2は実DLLで照合した。ゲーム内UI、Zenject実行順、Steam/Oculus実認証、VR実プレイと録画品質は未確認。

## BeatLeader履歴

`Source/manifest.json` のgameVersion変更と周辺実装を調査。`6c1016ca`（1.37.1）、`7aa8cad4`（1.37.3）、`a014ef3b`（1.37.4）を比較し、`70c4a02d` / `ecc7c732` の1.29.1への戻しを逆向きの移植に参照。FPS補正は `fbf1a1ff` を参照。ライセンスは同梱の第三者表示を参照。

## 成果物と実機確認

`build.ps1` が `artifacts/BS1.37.1/<日時>/` にZIP、DLL、ライセンス、ビルドログ、API照合、self-testログ、SHA256を出力する。ゲームへのコピーは行わない。

実機では対応Modを導入し、リーグ・SID・譜面を仮サーバfixtureと一致させて、Challenge予約→通常Play→Clear/Fail/Quit、Pause/Restart抑止、送信禁止、認証とOutbox再送信を確認する。実際のゲームを使う場合はテスト用リーグを使用する。

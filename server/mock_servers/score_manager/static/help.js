"use strict";
window.HELP = {
  active: ["開催中の実リーグ", "実 JBSL-WEB の /api/active_league を GET で取得します。isLive と isOpen が true のリーグを表示します。\n一覧の取得だけでは中継の設定は作成されません。「取込・設定」を開き、参加者や譜面の情報を確認して保存してください。通信に失敗した場合は前回取得日時とエラーを表示します。", "import"],
  sample: ["保存済み設定とサンプル", "サンプル3023はQualifier、3024は非Qualifier、3025は受付停止です。架空の譜面・SIDを使い、実サーバへの通信は発生しません。\n実リーグは取込時の応答も保存します。実中継モードでは毎回ランキングを取得し、保存応答モードでは取込時の応答を使用します。", "architecture"],
  enabled: ["Qualifier を有効にする", "有効にすると、すべての譜面に1〜100回の上限が必要です。無効時は提出方式を external_leaderboard、期間と上限を null にして返します。\n有効にしただけでは参加資格は成立しません。方式、受付状態、期間、MapKey、参加者SIDも照合されます。保存するたびに revision が増えます。", "eligibility"],
  method: ["提出方式", "JBSL Qualifier v1 は、このModからのチャレンジ結果を使う方式です。外部リーダーボードは通常方式です。\n有効チェックを残したまま外部方式にすると、wrong_submission_method の対象外判定を再現できます。", "eligibility"],
  open: ["リーグ稼働・受付状態", "isLive または isOpen をオフにすると正常な受付停止です。中継は HTTP 200、status は league_not_open、新規予約は拒否になります。\n受付停止だけで既存の予約は取り消しません。予約時に固定された受付期限まで結果を提出できます。", "eligibility"],
  window: ["期間と実効終了日時", "この画面の日時入力はすべて UTC です。日本時間は UTC + 9時間です。\n開始を空欄にすると追加の開始下限はありません。Qualifier終了が空欄ならリーグ終了を使います。両方あると Qualifier終了が優先されます（早い方を選ぶ計算ではありません）。実効終了は開始より後である必要があります。", "deadlines"],
  participants: ["参加者 SID", "1行に1人、数値化せず文字列で照合します。Steam / Oculus の認証結果と一致する SID を設定してください。空白や重複は保存時に拒否します。\n取込直後は空欄です。「現在のテスト SID を追加」でstub認証のユーザーを参加者にできます。実 JBSL-WEB の参加者を変更する操作ではありません。virtual・invite・ランキングのSIDから参加者を推測しません。", "import"],
  maps: ["譜面の対応と回数上限", "MapKey は hash・characteristic・difficulty の3要素です。lid（無い・重複する場合は取込時のindex）で元の譜面へ設定を重ねます。\n難易度は playlist_songs と lid + hash で一意に照合した場合だけ補います。不明な値は手入力してください。1つのリーグの同じMapKeyは重複できません。上限はユーザー×リーグ×譜面ごとです。", "maps"],
  characteristic: ["Characteristic", "Beat Saber の正式な選択値を入力します。Standard、OneSaber、NoArrows、360Degree、90Degree、Lawless、Lightshow などです。\n同じhashでも characteristic が違えば別のMapKeyです。", "maps"],
  difficulty: ["Difficulty", "Easy / Normal / Hard / Expert / ExpertPlus のいずれかです。画面上の Expert+ は API では ExpertPlus とします。hashだけから難易度を推測しません。", "maps"],
  song_duration_seconds: ["曲時間（秒）", "正の数値。未取得なら空欄（null）です。\nViewer の開始締切にはゲーム内の曲時間が使われます。ここで設定する時間は、サーバ開始判定を「実効終了 − 曲時間」にしたときの実験用です。曲時間不明時、このモックのサーバは実効終了のみで判定します。", "deadlines"],
  qualifier_attempt_limit: ["譜面別回数上限", "1ユーザーがそのリーグのこの譜面へ挑戦できる上限です。1〜100回、Qualifier無効時はnullです。\nConfirmの予約が確定すると1回消費します。開始失敗・quit・restartでも戻りません。上限を下げても消費済み回数は保持され、残りは最低0になります。", "attempts"],
  upstream_mode: ["実リーグの中継モード", "実中継: 保存済み設定を、毎回取得する実 JBSL-WEB のランキングに重ねます。\n保存応答: 取込時のランキングへ設定を重ねます。外部通信なしで再現できます。\n同梱サンプルは常に保存応答です。開催中一覧の手動更新は、どちらのモードでも実APIに接続します。", "architecture"],
  proxy_fault: ["中継の障害", "503到達不能、HTTP 200の壊れたJSON、429レート制限、404不存在を再現します。中継のleaderboard経路だけに適用します。\n管理画面と実リーグ一覧の更新には適用しません。壊れたJSONもログ上はエラーとして表示します。", "scenarios"],
  proxy_delay_ms: ["中継の遅延", "中継APIの処理を開始する前に待つ時間です。0〜60,000ミリ秒。障害設定と組み合わせられます。\nスコア管理サーバから中継へのタイムアウトは10秒です。10秒を超えると新規予約は上流障害となり、回数を消費しません。", "scenarios"],
  score_fault: ["スコア API の障害", "503一時障害、401認証要求、429レート制限を処理前に返します。該当する要求はDB処理へ進みません。\n401を結果提出だけに設定するとOutboxの再認証を試せます。「すべて」へ401を設定すると認証自体も失敗します。", "scenarios"],
  score_fault_route: ["スコア障害・遅延の対象", "障害と遅延を適用する経路です。すべて / 認証 / status / reserve / started / result を選びます。\nreserveだけを遅らせると、Viewerの予約待ちタイムアウト後に成功応答が届く状況を再現できます。", "scenarios"],
  score_delay_ms: ["スコア API の遅延", "選択した経路の処理前に0〜60,000ミリ秒待ちます。Viewerのタイムアウト設定より長くすると遅延応答を試せます。\nHTTP切断後も予約が成功する場合があります。回復を確認する際はログと消費済み回数も確認してください。", "scenarios"],
  stub_sid: ["テスト SID", "新しく認証するViewerへ返すSIDです。管理画面はログイン不要ですが、ViewerのAPI認証契約は維持しています。\n変更後は「Viewerセッションを失効」を実行して再認証してください。既存Challengeの所有者は変わりません。新しいSIDで試す際はリーグ参加者にも追加します。", "sessions"],
  stub_display_name: ["テスト表示名", "stub認証のauth/session・auth/meに返す名前です。新しい認証から反映されます。参加資格は名前ではなくSIDで照合します。", "sessions"],
  result_grace_seconds: ["結果提出の猶予 α", "結果受付期限 = 予約時の実効終了日時 + α（秒）。0〜604,800秒。\n期限は予約時に固定するため、保存後に猶予やリーグ期間を変更しても既存ChallengeのresultAcceptUntilは変わりません。本番未確定の試験用設定です。", "deadlines"],
  result_deadline_equal_is_accepted: ["受付期限ちょうどの判定", "オンなら受信時刻が受付期限と一致した場合も受理。オフなら一致から期限切れです。既存Challengeにも次の要求から適用します。\n元の結果を受理済みでも、期限後の再送は409です。本番未確定の試験用設定です。", "deadlines"],
  challenge_timeout_seconds: ["予約からの運用タイムアウト", "空欄は無効です。1〜604,800秒。予約時刻からこの時間が経過した結果提出をabandonedとして拒否します。\nこの既存モックの試験ポリシーは要求時に参照するため、既存Challengeにも次の提出から適用します。回数は戻しません。", "deadlines"],
  server_start_deadline_policy: ["サーバの開始締切ポリシー", "実効終了のみ: サーバは終了まで新規予約を受け付けます。\n実効終了 − 曲時間: 設定したsong_duration_secondsを差し引きます。nullなら実効終了のみです。\nViewerは別にゲーム内曲時間で開始締切を判定します。この選択はサーバの未確定ポリシーを試すものです。", "deadlines"],
  cache_fresh_seconds: ["通常キャッシュ期限", "statusが検証済みリーグ情報を再利用できる取得後の秒数です。0〜3,600秒。既定60秒。保存後の設定がすぐstatusに見えない場合はキャッシュを消去してください。\n新規reserveはこの値に関係なく、毎回中継から最新情報を取得します。", "cache"],
  cache_stale_seconds: ["参考キャッシュ期限", "上流へ到達不能のときだけstatusで参考表示する、取得時刻からの総秒数です。通常期限に加算する値ではありません。\n不正JSONには利用しません。stale=trueの表示で新規予約を許可せず、reserveは最新取得に失敗すると拒否します。", "cache"],
  session_seconds: ["Viewer セッションの寿命", "新しく発行するCookieセッションの有効秒数です。1〜86,400秒。短くすると自動再認証を試せます。既存セッションの期限は変更しません。", "sessions"],
  rate_limit_enabled: ["通常のレート制限", "オンで既存モックの固定制限（1分あたり認証5、status30、予約10、started20、result10）を使います。\n100件同時予約などの競合試験ではオフにしてください。障害注入の429はこの設定と独立です。", "scenarios"],
  clock_offset_seconds: ["スコアサーバの時計差", "OSの時刻は変更せず、スコアサーバが見るUTCを指定秒数だけ進める／戻します。±31,536,000秒。認証期限・キャッシュ・予約・結果期限に影響します。\nViewerの時計と実リーグ一覧の取得日時は変わりません。境界の厳密な一致は自動テストで検証します。", "deadlines"],
  connection: ["Viewer の接続先", "leaderboardApiUrlは中継の /leaderboard/api/、scoreServerBaseUrlはスコアAPIのルートにします。HTTP loopback用のallowDevelopmentHttpをtrueにします。\n管理用ポートをViewerの接続先へ指定しないでください。ポートを変更する場合は起動引数を使い、ここに表示される値をコピーします。", "architecture"],
  logs: ["中継ログ", "中継・実JBSL-WEB・スコアAPI・管理操作を直近1,500件までメモリに保持します。再起動すると消えます。HTTP status、所要時間、出所、Request ID、エラーコードを確認できます。\nCookie、ticket、認証キー、クエリ文字列、要求本文、リプレイは記録しません。JSONプレビューはリーグ設定画面またはSwagger UIで確認してください。", "logs"],
  cache: ["キャッシュを消去", "スコアサーバの検証済みリーグキャッシュだけを削除します。次のstatusは中継へ再取得します。\nリーグ設定保存時は自動消去しません。60秒キャッシュの再利用を試すためです。消費済み回数や提出結果には影響しません。", "cache"],
  sessions: ["Viewer セッションを失効", "現在のViewer Cookieセッションを失効させ、次の通信で401と再認証を再現します。管理画面にログインは必要ありません。\nChallengeや結果は削除せず、所有者SIDも変わりません。", "sessions"],
  rate: ["レート制限履歴を消去", "直近1分のリクエスト数の履歴をクリアします。通常制限による429からすぐ復帰できます。\n障害注入で設定した429は解除されません。サーバ挙動で障害を「なし」に戻してください。", "scenarios"],
  budgets: ["消費済み回数", "消費済み回数と、最後の予約時点で保存された上限を表示します。リーグ設定を変更した直後は、表示の上限と現在の上限が異なる場合があります。\n最新の残回数はSwagger UIのstatusで取得してください。回数はSID×リーグ×MapKeyごとに独立します。", "attempts"]
};
Object.assign(window.HELP,{"upstream_base_url": ["リーグ取得先 URL", "中継APIのベースURLです。既定は http://127.0.0.1:18080。保存後の取得から反映されます。接続先が異なるキャッシュは使いません。\n接続確認は保存済み設定でGETし、回数を消費しません。外部にはHTTPSを指定してください。", "architecture"], "upstream_timeout_seconds": ["リーグ取得のタイムアウト", "リーグ取得時に通信を待つ秒数です。中継の遅延より短く設定すると上流タイムアウトを再現できます。", "scenarios"], "compressed_replay_limit": ["圧縮リプレイの上限", "gzipで送信するreplayファイルの上限バイト数です。既定16 MiB（16,777,216バイト）。超過は413で拒否します。", "uploads"], "expanded_replay_limit": ["展開後リプレイの上限", "gzipを展開したBSORの上限です。既定128 MiB（134,217,728バイト）。小さくすると展開後のサイズ超過を試せます。", "uploads"], "metadata_limit": ["メタデータの上限", "結果メタデータJSONの上限です。既定512 KiB（524,288バイト）。低い上限で提出失敗と再送を確認できます。", "uploads"], "challenge_status": ["Challengeの状態", "reservedは予約済み、startedは開始通知済み、submittedは結果受理済みです。abandonedは受付期限切れです。\n期限切れ表示はスコアサーバ時計と期限ポリシーから計算します。閲覧だけではDBを変更しません。詳細にはDB保存状態も表示します。", "lifecycle"], "filters": ["一覧の絞り込み", "リーグIDとSIDは完全一致、Challenge ID / hashは部分一致です。空欄はすべて。1ページ25件でページを移動できます。自動更新は表示中のページだけに適用します。", "inspection"], "audit": ["受付履歴", "受理した予約・開始・提出に加え、認証・予約・提出を拒否した理由コードを確認できます。API通信ログと違い再起動後も残ります。\n認証ticketやCookieは保存・表示しません。Challengeが作られなかった拒否にはリンクがありません。", "inspection"], "ranking": ["ランキング採用可否", "validForRankingがtrueの受理済み結果を採用対象と表示します。対象外でも提出を受理した結果は残り、回数は返還されません。\nこの仮サーバはBSORの基本識別情報を検証します。点数の完全な再計算は実装していません。", "inspection"], "metadata": ["提出メタデータ", "Viewerから届いたスコア・ミス・コンボ・修飾・時刻・提出可否をそのまま確認します。nullは未送信で、0点と区別します。UTC原文はJSONで確認できます。", "inspection"], "replay": ["リプレイ保存状態", "受信したgzipは展開してBSORとして保存します。ハッシュとサイズは展開後データの値です。ファイル有無はこの仮サーバの保存先で確認します。", "uploads"], "connection": ["接続先", "ViewerのscoreServerBaseUrlをこの仮スコアAPIに設定します。leaderboardApiUrlは中継側の画面で確認してください。\n実スコアAPI18081・管理18763とは別のサーバです。各起動バッチで個別に起動・停止します。", "architecture"]});
document.addEventListener("click", event => {
  const button = event.target.closest("[data-help]");
  if (!button) return;
  const info = window.HELP[button.dataset.help];
  if (!info) return;
  document.getElementById("help-title").textContent = info[0];
  document.getElementById("help-text").textContent = info[1];
  document.getElementById("help-link").href = "/guide#" + info[2];
  document.getElementById("help-dialog").showModal();
});
document.getElementById("close-help")?.addEventListener("click", () => document.getElementById("help-dialog").close());

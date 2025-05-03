# JBSLViewer
このBeatSaberプラグインは[JBSL-Web](https://jbsl-web.herokuapp.com/)の情報を表示します。

![image](https://github.com/user-attachments/assets/03c01179-40c5-45e3-a5e4-eee59ba9d157)

現在は、Live Leaguesのリーダーボードを表示する機能があります。

## 特徴
* Headlinesの最新更新日時を基準にして、10分毎に自動更新します

# インストール方法
1. [リリースページ](https://github.com/rynan4818/JBSLViewer/releases)最新のJBSLViewerのリリースをダウンロードします。
2. ダウンロードしたzipファイルを`Beat Saber`フォルダに解凍して、`Plugin`フォルダに`JBSLViewer.dll`ファイルをコピーします。
3. [LeaderboardCore](https://github.com/rithik-b/LeaderboardCore)に依存するので、Mod Assistantでインストールして下さい。[BeatLeader](https://github.com/BeatLeader/beatleader-mod) modをインストールしている人は既に導入されています。

# 使い方
右のリーダーボードにJBSL-Webのリーダーボードが追加されます。

* `LEAGUE RELOAD`ボタンはLive Leaguesのリストを更新したい場合に使用します。同時にHeadlinesの最新更新日時も取得し直します。
* `BOARD RELOAD`ボタンは手動でLeaderboardを更新したい場合に押します。
* `Auto Reload Time`は次回更新までの時間です。
* `JBSL League`ドロップダウンはリーグを選択します。
* `Leaderboard`ドロップダウンはリーダーボードを選択します。
* `TOTAL`ボタンはリーダーボードを合計順位に切り替えます。
* `🔼`ボタンは前のページに移動します。
* `🔽`ボタンは次のページに移動します。

# 今後追加予定の機能
* ユーザーアイコンの表示
* 自分のスコアをハイライト表示
* 選択中譜面とリーダーボードの連動
* プレイリストダウンロード機能
* 終了したリーグの閲覧機能

# Phase 5 新作・セール5選 ローカル実装報告

- 実施日: 2026-08-08
- 状態: Gemini実リサーチ、10候補提示、人による5本選択、下書き生成、Discord手動投稿、PDF添付Webhookを実装。Obsidian保存、schedule、公開は未実施

## 変更前の基準

- Phase 0〜4完了、既存67テスト成功
- Hugo 0.163.2 extended本番相当ビルド成功
- Gitは`main`、`origin/main`と一致し、作業ツリーとstageに変更なし
- Obsidianの記事候補は2件、週次記事と私感欄は0件
- Phase 5と競合するWindowsタスクはなく、GitHub Actionsは毎朝8時ビルドのみ

## 情報取得方式

Steamworks公式Web APIには、一般向けの今週発売・セール全作品を取得する安定した公開公式カタログAPIを確認できなかった。Apifyも比較したが、コミュニティActorの保守、地域価格、HTML変更への追従が必要になるため、ユーザー判断で当面は手入力とした。

候補発見はSteamの近日中リリース、スペシャル、ウィッシュリストを使い、SteamDB等は発見と価格履歴の補助だけにする。最終根拠はSteam、開発元、販売元の公式ページとする。外部API料金、APIキー、レート制限は発生しない。

## 確定した定義

- Asia/Tokyoの月曜00:00から日曜23:59:59を対象週とし、日曜24時は翌月曜00:00
- 週IDはISO週`YYYY-Www`、slugは`weekly-picks-yyyy-www`
- 日本地域、日本円、Steam表示の税込価格を基準
- セールは通常価格と現在価格から再計算して20%以上
- 無料、デモ、DLC、サウンドトラック、バンドルは初期対象外。早期アクセスは明記すれば許可
- 日本語はインターフェイス、字幕、フル音声を別々に記録
- 新作とセールを最低1本ずつ含め、残りは編集優先度、作品名、App IDで決定
- 5本未満なら停止し、架空作品や条件未達作品で補完しない

## 安全な下書き

`scripts/weekly_picks.py`は手入力JSONを検証し、新規出力フォルダへ原子的に`index.md`、非公開証跡、AI dry-run入力、7時30分・20時用SNS素材を作る。既存出力先を上書きせず、失敗途中のフォルダを完成下書きとして残さない。記事は常に`draft: true`で、未プレイ記事かつレビューでないことを明記する。

私感は専用欄に保持し、AI許可リストへ含めない。AIへ渡せるのは検証済み事実、公式URL、確認日時、短い編集文脈だけである。AI応答は事実ハッシュと一致し、許可した文章欄だけを持つ場合に限り受け付ける。現時点で実AI送信は0件である。

同じ週の生成・公開履歴、App ID、正規化Steam URL、過去掲載App IDを検査する。公式情報なし、矛盾、発売延期、価格変動、候補不足、重複は要確認相当、ネットワーク、保存、ロック等はエラー相当の固定分類を用意した。通知内容は週ID、固定理由、件数だけに限定する。実Discord送信は0件である。

## 実行場所と時刻

初期運用はWindows上の手動dry-runで開始する。日曜24時まで私感を受け付けられるが、私感が空でも下書きは作れる。月曜6時のscheduleと完全自動公開は登録・有効化していない。将来有効化する場合も月曜6時は検証済み下書きとローカルSNS素材生成までとし、公開は既存の記事単位承認を必要とする。

## Geminiリサーチ確認資料

`scripts/weekly_research.py`を追加し、Google検索とURL参照を使う構造化Geminiアダプター、最大12候補・検索20回の受入上限、既存Phase 5検証への接続を実装した。通過後はローカルHTML、Discord閲覧用PDF、メンション無効の3行要約JSONを作る。Discord送信機能はまだ有効化していない。

APIキーは既存の`GEMINI_API_KEY`だけから読み、会話保存を無効化する。モデルは既存方針と同じ`gemini-3.6-flash`へ固定した。月500円を警告、月1,000円を停止判断の目安とするが、Cloud Billingの予算通知は自動停止ではない。

2026-08-08に、ユーザー承認のもと校正用キーを流用した接続診断を実施した。キー、Tier 1、`gemini-3.6-flash`、Google検索ツールの受付は成功した。一方、候補調査結果は検索回数の安全上限を満たすと確認できず不採用とし、HTML/PDFを生成せず停止した。以後はAIの自己申告ではなくAPIの`google_search_call`実行記録を数えるよう修正した。実Discord、Drive、公開は0件のままである。

同日の実候補テストでは、Geminiが新作候補へセール専用項目を設定したため1回目は停止した。新作のセール専用欄だけを決定的に除去する処理を追加後、2回目は確認日時にタイムゾーンがなく停止した。いずれも外部検索は成功したが、厳格な候補検証を通過していないため実HTML/PDFは生成していない。連続再試行による費用増加を避け、実検索はここで停止した。

その後ユーザー承認により、Geminiは候補と出典の収集、PythonはApp ID、対象週からの新作・セール区分、整数円価格、割引率、JP/JPY、JST確認日時、日本語対応形式、一次情報URLを整理する二段階方式へ変更した。形式不明・無料・20%未満・公式Steam URLなしの候補は除外し、残りを既存の厳格検証へ渡す。全104テスト成功後の実リサーチ1回で、6候補から5件を選定し、ローカルHTML、PDF、Discord要約JSONの生成に成功した。PDFは1ページを画像化して日本語、折り返し、欠落がないことを目視確認した。実Discord、Drive、公開は0件のままである。

運用確認後、AIによる最終5本の自動選定をやめ、新作候補5本とセール候補5本を目標に提示し、人が合計5本を選ぶ方式へ変更した。HTMLとPDFはカテゴリ別のチェック欄付き一覧、`selection.json`は候補App ID一覧と空の`selected_app_ids`を持つ。候補不足は実在確認できた本数を表示して注記し、架空候補では補わない。全105テストとHugo本番相当ビルドに成功し、2ページPDFを画像化して候補カードがページ境界で分断されないことを確認した。この変更後の実Gemini再検索は行っていない。

同日、ユーザー承認後に変更後の実Geminiリサーチを1回実行し、新作5件・セール5件の計10件を取得した。カテゴリ別HTML、2ページPDF、メンション無効のDiscord要約JSON、未選択の`selection.json`を生成し、PDF全ページを画像化して日本語、価格、URL、チェック欄、改ページを目視確認した。記事への採用、実Discord送信、Drive保存、公開は行っていない。

ユーザーが候補番号1・2・3・8・9を選択したため、新作3件・セール2件を`selection.json`へ記録した。選択候補を再度厳格検証し、`output/weekly-picks-2026-w32-draft/`へ`draft: true`の記事、非公開証跡、AI dry-run入力、SNS素材を新規生成した。Obsidian、公開記事、Git履歴は変更していない。

ユーザーの実送信承認後、Discordサーバー`LABdeLIC`の既存`編集室`カテゴリへ`週次リサーチ`テキストチャンネルを新規作成した。選択した5作品の要約、`draft: true`、公開前再確認の注意書き、10候補比較PDFを1メッセージとして投稿し、Discord画面上で本文とPDF添付を確認した。実Discord投稿は1件、チャンネル作成は1件。Drive保存、記事公開、SNS投稿、commit、pushは行っていない。

## テストと外部変更

追補として、`research-result.json`へ検証済み候補を保存し、`selection.json`の5本を再検証して下書きへ接続する`apply_weekly_selection.py`を追加した。Discord要約とPDFを専用Webhookで送る`weekly_research_notify.py`、固定文面の接続テスト用GitHub Actionsも追加した。Secret名は`DISCORD_WEBHOOK_WEEKLY_RESEARCH`で、値はリポジトリ・ログ・Discord本文へ残さない。

専用Secretを値を表示せずGitHubへ登録後、Actions run `31248848194`から固定の接続テスト文面と架空候補PDFを1件送信した。jobは成功し、Discordの`週次リサーチ`で`AI編集部`アプリによる本文とPDF添付を確認した。初回runで公式Action旧版のNode.js 20警告が出たため、既存リポジトリ方針と公式案内に合わせて`actions/checkout@v6`と`actions/setup-python@v6`へ更新した。更新後のrun `31248928366`も警告なしで成功し、Discord上の2件目を確認した。

- 全116テスト成功。テスト内の候補・AI・Discordはfakeで、実サービスを呼ばない
- 変更前の既存67テスト: 成功
- Phase 5追加後の全116テスト: 成功
- Hugo 0.163.2 extended本番相当ビルド: 成功（既知の将来廃止予定警告1件のみ）
- 実Geminiリサーチ: 承認済みの限定実行。最終実行で新作5件・セール5件を取得
- Obsidianへ作成・変更したファイル: 0件
- 実Discord: チャンネル作成1件、手動投稿1件、Webhook接続テスト2件。実SNS・実公開: 各0件
- Windowsタスク、GitHub Actions schedule: 変更なし
- Phase 4バックアップ、既存公開、原稿、画像、PaperMod、独立した`my-blog`: 変更なし
- commit、push、Actions、公開: 未実施

## 保留とPhase 6

### 公式再確認とObsidian配置（追補）

初回選択5本を公開前に独立してSteam公式情報と照合したところ、`つんつんリリム`の発売日が「近日登場」へ変わり、Coffee Talkとして扱ったApp ID `1090100`が実際にはScorchlandsであることを確認した。この時点で旧下書きのObsidian配置と公開を停止した。

Gemini実リサーチを1回だけ再実行し、新作5件・セール5件を再生成してDiscordへPDFをWebhook投稿した。ユーザーは1・4・5・9・10を選択した。独立照合ではAkatoriの最新Steam表示が日本語未対応だったため、インターフェイス・字幕・音声をすべて未対応へ修正した。その後、Re:Night、Big Walk、Akatori、Marvel's Spider-Man: Miles Morales、NieR:Automataの5本で最終下書きを再生成した。

最終下書きはUTF-8、5本、`draft: true`、旧誤候補なし、日本語修正反映を機械確認し、`C:\Users\ymmt_\Documents\Life_and_Div\30_Projects\01_blog\weekly-picks-2026-w32\index.md`へ新規配置した。生成元と配置先のSHA-256一致を確認した。記事公開、SNS投稿、`draft: false`変更は行っていない。

ユーザー承認により、毎週日曜18時（Asia/Tokyo、cronは日曜09:00 UTC）にGeminiで10候補を調査し、Discordへ要約とPDFを送るGitHub Actions scheduleを追加した。選択用の全成果物は14日間保存する。scheduleは記事生成、公開、SNS投稿を行わない。

GitHub Secret `GEMINI_API_KEY`を値を表示せず登録し、本番相当の手動run `31249575323`を実行した。Gemini調査、候補検証、成果物`weekly-research-2026-W32`の14日間保存、Discord PDF通知まで全stepが約2分で成功した。workflowが有効であることも確認した。

公開経路テスト後の通常運用では、記事内容の人による確認と記事単位の明示承認を引き続き必要とする。Phase 6は先行実装しない。

### 公開経路の実地確認（追補）

ユーザーが`weekly-picks-2026-w32`の公開を明示承認した。公開直前のSteam公式API確認ではMiles Moralesのセール終了を検出したが、ユーザーから今回は情報記事の正確性ではなく実装経路のテストであるとの判断を受けた。このため、タイトルと冒頭へ動作確認用であること、価格・セール状況は現在と異なる場合があることを明記して公開した。

既存の`publish.ps1 -Approve`により、校正レポートなしとOGP画像なしを警告として表示し、停止0件で同期、production検査、Hugo生成、生成HTML検査を通過した。対象記事だけをcommit `bb293e8`（`publish: weekly-picks-2026-w32`）としてpushした。Actions run `31250106253`のbuild、deploy、記事URL verify、`公開通知`jobはすべて成功し、公開URLのHTTP 200、動作確認タイトル・注意書きを確認した。SNS投稿は行っていない。

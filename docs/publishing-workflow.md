# 記事のプレビューと公開手順

> 端末障害・誤削除からの復元は [`backup-and-restore-workflow.md`](backup-and-restore-workflow.md) を参照してください。Phase 4のGoogle Driveバックアップと定期実行は有効化・検証済みです。

この文書は、Phase 1の安全な公開基盤、Phase 2の本文を書き換えない校正レポート、Phase 3のGitHub Pages確認後のDiscord通知について、現在の使い方をまとめたものです。

## 原稿の置き方

Obsidianの `Life_and_Div/30_Projects/01_blog` に、記事ごとのフォルダを作ります。

```text
01_blog/
└─ sample-game/
   ├─ index.md
   ├─ review-report.md
   └─ images/
      └─ 01.png
```

- 公開本文は `index.md` です。
- `review-report.md` は校正記録です。同期処理が常に除外します。
- 画像は記事ごとの `images/` に置きます。
- `![[01.png|説明]]` と書いた画像は、記事用の相対リンクへ変換されます。

## front matter

執筆中は `draft: true` にします。

```yaml
---
title: 記事タイトル
date: 2026-08-01
lastmod: 2026-08-01
draft: true
description: 記事の短い説明
images: []
article_type: play_note
play_time: 約5時間
spoiler_warning: ""
provided: false
author: やまもと
corrections: []
---
```

公開する準備ができたら、Obsidian上で `draft: false` に変更します。公開処理は `draft: false` が明示されていない記事を拒否します。

### 3種類の雛形

| 記事 | Hugoのkind | `article_type` | 固有の項目・表示 |
|---|---|---|---|
| プレイ途中記 | `play-note` | `play_note` | `play_time` が必須。プレイ時間と完走レビューではない旨を自動表示 |
| 新作・セール5選 | `weekly-picks` | `weekly_picks` | 未プレイ作品の紹介でありレビューではない旨を自動表示 |
| 月次レビューエッセイ | `monthly-essay` | `monthly_essay` | 常設の注意枠を出さず、文章を優先 |

たとえば、プレイ途中記のPage BundleをObsidian原稿フォルダへ作る場合は次を実行します。

```powershell
hugo new content --kind play-note sample-game/index.md --contentDir "C:\Users\ymmt_\Documents\Life_and_Div\30_Projects\01_blog"
```

`sample-game` を記事slugへ置き換えてください。ほかの2種類はkindだけを変えます。

- `images` の1枚目はOGP画像に使われます。画像なしなら `[]` のままで安全に表示できます。
- `spoiler_warning` は、必要なときだけ具体的な警告文を入れます。
- `provided: true` の場合だけ提供表示が出ます。
- 内容に関わる訂正では `lastmod` を更新し、`corrections` に `date` と `summary` を追加します。

## 画像の扱い

JPEG、PNG、WebPは公開ビルド時に縮小版とWebPを自動生成し、画面幅に合う画像を配信します。Obsidianの元画像とPage Bundleの元画像は上書きしません。透過PNGは元PNGも残し、GIFはアニメーション維持のため変換せず、SVGとAVIFもそのまま扱います。変換物は生成領域に置かれるため、再実行だけでGit差分は増えません。

## 校正レポート

校正は本文を直す処理ではありません。AIは6分類の指摘と修正案を `review-report.md` へ書き、採用するかはユーザーが決めます。

1. 誤字・脱字
2. 主語述語や日本語の違和感
3. 読者が理解しにくい箇所
4. 事実確認が必要な箇所
5. SEO上の提案
6. 構成上の提案

指摘がない分類には「指摘なし」と表示されます。各指摘には重要度、該当箇所、修正理由、修正案があります。最後のチェック欄を見ながら、採用したい修正だけをObsidianの `index.md` へ自分で反映してください。

### 現在の開始方法

初期AIはGoogle Gemini Developer APIの安定版 `gemini-3.6-flash` に決定しました。APIキーはまだ用意していないため外部接続は無効です。キー取得までの暫定運用は、Codexで「記事slugをPhase 2の方式で校正して」と依頼し、構造化した結果を安全な取込処理へ渡す手動方式です。Codexは本文へパッチを当てず、取込処理だけが `review-report.md` を保存します。

Geminiの無料枠では、送信内容がGoogleの製品改善に使われる扱いです。記事本文を送る前に、この条件と最新の無料枠を再確認します。Google検索連携は無料枠では利用できないため、自動校正では無効にします。Interactions APIの会話保存も無効にします。

### APIキーの設定

APIキーはリポジトリ、`.env`、PowerShell履歴、Obsidian、レポートへ書きません。Windowsの「環境変数を編集」を開き、ユーザー環境変数として名前 `GEMINI_API_KEY`、値に取得したAPIキーを設定します。設定後はCodexとPowerShellをいったん閉じ、新しいプロセスで開き直します。

キーの値をチャットへ貼らないでください。設定確認では環境変数名の有無だけを表示します。

最初の実通信は、実記事ではなく短い架空原稿を1回だけ送ります。

```powershell
python scripts\gemini_smoke_test.py
```

2026-08-02にこの疎通テストは成功しました。架空原稿だけを送信し、本文変更なし、6分類レポート、一時データ削除を確認済みです。公式SDKからInteractions APIが試験的で将来変更される可能性があるという警告が出るため、SDK更新時は再テストします。

成功後、実記事を校正する操作は次のとおりです。

```powershell
.\review.ps1 -Article sample-game -Gemini
```

### 手動確認用の記事

Obsidianの `01_blog/phase2-review-demo/index.md` に、公開されない `draft: true` の架空記事を用意しています。誤字、意味の矛盾、曖昧な説明、未確認の売上情報、見出し不足を意図的に含めています。

1. Obsidianで `phase2-review-demo/index.md` を開く
2. 校正前の本文を確認する
3. `Ctrl+Alt+K` を押す
4. 確認画面の内容を読み、「はい」を選ぶ
5. 別画面で校正完了と本文ハッシュ不変を確認する
6. 同じ記事フォルダにできた `review-report.md` を開く
7. 6分類、重要度、理由、修正案があることを確認する
8. `index.md` が変更されていないことを見比べる

このデモ記事は `draft: true` と `test_content: true` のため、本番公開できません。手動確認後も自動削除はしません。

PowerShellでAIへ渡す対象だけを確認する場合:

```powershell
.\review.ps1 -Article sample-game -DryRun
```

校正用の構造化入力全体を画面で確認する場合:

```powershell
.\review.ps1 -Article sample-game -PrintRequest
```

固定応答を使う動作確認は次のとおりです。これは文章を校正せず、6分類の空レポートを作るテスト専用です。

```powershell
.\review.ps1 -Article sample-game -Fake
```

AIが返したJSONを取り込む場合は、`data/editorial/review-response-template.json` と同じ形式にし、使用したサービス・モデルを実在する情報だけで記録します。

```powershell
.\review.ps1 -Article sample-game -ResponseFile C:\path\to\response.json -Method "実際に使用したサービスとモデル"
```

既存のレポートが異なる結果の場合は自動上書きしません。確認して置き換える場合だけ末尾へ `-Replace` を付けます。同じ原稿・同じ設定・同じ結果なら既存ファイルを再利用し、日時だけの差分を作りません。履歴は複数ファイルへ増やさず、記事ごとに1つのレポートを明示的に置き換えます。

### 本文を修正した後

本文を修正すると、レポート内のハッシュと現在の `index.md` が一致しなくなり、「古いレポート」と表示されます。これは異常ではなく、「今の本文はまだこのレポートの対象ではない」という意味です。再校正して新しい結果を確認してください。

```powershell
.\review.ps1 -Article sample-game -Status
```

レポートがない、または古い場合は警告ですが、それだけでは公開を止めません。秘密情報の疑い、壊れたレポート、危険なHTML、校正中の本文変更、保存失敗は停止します。

### AIへ渡す情報

送信対象は、指定した1記事の許可済みfront matter、本文、記事種別、description、プレイ時間、ネタバレ・提供表示、画像のファイル名と代替テキストです。画像ファイル本体は送りません。

送らないものは、APIキー、Webhook URL、Git認証情報、Obsidian全体、別の記事、過去のレポート、`.git`、`.env`、OSのユーザー情報、ブログ以外の個人メモ、画像本体、独立した `my-blog` のデータです。入力前と保存前に秘密情報らしい文字列を検査し、見つかった場合は値を表示せず、種類と場所だけを知らせて停止します。

## プレビュー

現在は次のように実行します。`sample-game` は記事フォルダ名です。

```powershell
.\preview.ps1 -Article sample-game
```

Obsidian設定の切替後は、記事の `index.md`、`review-report.md`、または記事画像を開いて `Ctrl+Alt+V` を押すと同じ処理を実行できます。

プレビュー開始前に校正レポートの有無・鮮度・安全性も確認します。レポートなし・古いレポートは警告だけです。プレビュー用データはWindowsの一時フォルダに作られ、`review-report.md` は同期されません。Hugoの正式な `content/posts/` やGitには触れません。表示確認後、PowerShell画面で `Ctrl+C` を押すと終了します。

## 公開

公開処理はプレビューとは別です。

```powershell
.\publish.ps1 -Article sample-game -Approve
```

Obsidian設定の切替後は、対象記事を開いて `Ctrl+Alt+P` を押します。確認画面を承認した場合だけ、別ウィンドウで公開処理が始まります。

公開処理は次の順で進みます。

1. 明示的な `-Approve` があるか確認
2. 既存のstage済み変更がないか確認
3. 公開先の記事に未コミット変更がないか確認
4. 指定した1記事をWindows一時フォルダのPage Bundleへ同期
5. 校正レポートの有無・鮮度・安全性を確認
6. `draft: false`、front matter、画像、内部リンク、テスト記事を検査
7. 一時フォルダで本番相当のHugoビルドを実行
8. title、description、canonical、OGP、Twitter Card、JSON-LD、サイト内リンク、sitemap、robots.txt、RSSを生成HTMLで検査
9. 全検査の成功後、正式なPage Bundleへ同期し、指定記事だけをGitへ登録
10. `publish: 記事slug` という記事単位のcommitを作成
11. GitHubへpush
12. 対応するGitHub Actionsの完了を最大10分待つ
13. Actionsでbuild、deploy、PagesトップURL、対象記事URLを順に確認
14. `publish: 記事slug` と変更範囲が安全に一致したpushだけ、Discordの `公開通知` へ送信

`.gitignore`、仕様書、別の記事など、指定記事以外の変更はcommit対象にしません。

検査結果は `[停止]` と `[警告]` に分かれます。必須情報不足、画像・内部リンク切れ、`review-report.md` 混入、SEOメタ情報の欠落や重複、下書き・新規テスト記事の誤公開、レポート内の秘密情報や不正形式は停止します。レポートなし・古いレポート、画像未設定、過去に意図して公開したnoindex付きテスト記事、文章上の提案は警告に留めます。

## Discord通知

GitHub Actionsで使用するSecret名は次の3つです。値はGitHub Secretsだけへ登録し、チャット、コマンド、ログ、ファイルへ表示しません。

| Secret名 | チャンネル | 通知条件 |
|---|---|---|
| `DISCORD_WEBHOOK_PUBLISH` | `公開通知` | HEADが `publish: <安全なslug>` でpush全体が対象記事だけ、かつbuild、deploy、Pagesトップ、対象記事URL確認まで成功 |
| `DISCORD_WEBHOOK_ERROR` | `エラー通知` | push、毎朝のschedule、手動実行のbuild、deploy、URL確認、通知が技術的に失敗 |
| `DISCORD_WEBHOOK_ATTENTION` | `要確認` | `publish:` で始まるpushだがslugまたは変更範囲を安全に特定できず、deployとPages確認は成功 |

通常のコード・資料push、毎朝8時のschedule、Actions画面からの手動実行は、成功しても `公開通知` を送りません。校正レポートなし・古いレポートをGitHubへ安全に渡す方式は未決定なので、現時点では `要確認` の条件に含めません。

通知に含めるのは、通知種別、記事slugまたは失敗段階、公開URL、commitの短い識別子、トリガー、Actions実行URLだけです。記事本文、校正レポート本文、Webhook URL、秘密情報、ログ全文は送りません。`@everyone` 等が文字列に含まれてもメンションとして処理されない設定です。

Discordが429または5xxを明示的に返したときだけ、初回を含め最大3回試します。400、401、403等の4xxや、結果が分からない通信切断・タイムアウトは重複防止のため再試行しません。Actions全体を手動で再実行した場合は同じ通知が重複する可能性がありますが、commitとActions実行URLで見分けられます。

通知に失敗した場合、Actionsは失敗として表示されます。ただし、すでに公開された記事、Git commit、GitHub Pagesを削除・revertしません。公開通知または要確認通知の失敗は、可能なら `エラー通知` に通知します。

## 現在のショートカット

- `Ctrl+Alt+V`: 現在開いているゲームブログ記事を一時領域でプレビュー
- `Ctrl+Alt+K`: 確認後、現在開いているゲームブログ記事をGeminiで校正
- `Ctrl+Alt+P`: 確認画面の承認後、現在開いているゲームブログ記事を公開
- `Ctrl+Alt+L`: 確認画面の承認後、既存のlogsブログ（`my-blog`）を公開

校正専用ショートカットは `Ctrl+Alt+K` です。対象記事の `index.md`、`review-report.md`、または画像を開いて押すと、本文送信と既存レポート置き換えの確認画面が出ます。「はい」を選んだ場合だけGemini校正を開始し、結果を別のPowerShell画面へ表示します。校正をプレビューとは独立させ、`Ctrl+Alt+V` はプレビューと状態確認に限定します。

## エラー時の確認

- `[警告] 校正レポートがありません`: 必要なら校正する。確認済みならそのままプレビュー・公開可能
- `[警告] 古い結果`: 本文修正後のため、再校正を推奨
- `秘密情報の可能性`: 表示された種類と行だけを手掛かりに、本文またはAI応答を確認。値はログに表示されない
- `AI出力を安全に解析できません`: JSONがテンプレートの6分類形式か確認
- `既存のreview-report.mdがあります`: 内容を確認し、置き換える場合だけ `-Replace`
- `index.mdが変更された`: 校正処理を止め、Obsidianで意図した編集か確認してから再実行
- Phase 1の画像・front matter・リンク・Hugoエラー: 従来どおり該当箇所を修正して再プレビュー

## Phase 3の確認結果

- 3つのGitHub Secretsは登録済みです。
- 2026-08-02に、`--test-message` で「接続テスト」「実際の公開・失敗・要確認は発生していない」と明記し、3チャンネルへ各1件・合計3件送り、全件成功しました。
- Phase 3のcommit、push、GitHub Actions、GitHub Pages反映を確認済みです。
- Pages公式ActionはNode.js 24対応のv5へ更新し、Node.js 20警告がない状態でbuild、deploy、URL確認に成功しました。

## 現在まだ行わないこと

- Obsidianから原稿を削除しても、公開記事は自動削除しません。

## テスト用の実行

`-NoPush` は開発・検証専用です。commitまでは作成するため、通常の手動確認には使わないでください。

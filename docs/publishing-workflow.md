# 記事のプレビューと公開手順

この文書は、Phase 1で導入した安全な公開基盤の現在の使い方をまとめたものです。

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

## プレビュー

現在は次のように実行します。`sample-game` は記事フォルダ名です。

```powershell
.\preview.ps1 -Article sample-game
```

Obsidian設定の切替後は、記事の `index.md`、`review-report.md`、または記事画像を開いて `Alt+Shift+V` を押すと同じ処理を実行できます。

プレビュー用データはWindowsの一時フォルダに作られます。Hugoの正式な `content/posts/` やGitには触れません。表示確認後、PowerShell画面で `Ctrl+C` を押すと終了します。

## 公開

公開処理はプレビューとは別です。

```powershell
.\publish.ps1 -Article sample-game -Approve
```

Obsidian設定の切替後は、対象記事を開いて `Alt+Shift+P` を押します。確認画面を承認した場合だけ、別ウィンドウで公開処理が始まります。

公開処理は次の順で進みます。

1. 明示的な `-Approve` があるか確認
2. 既存のstage済み変更がないか確認
3. 公開先の記事に未コミット変更がないか確認
4. 指定した1記事をWindows一時フォルダのPage Bundleへ同期
5. `draft: false`、front matter、画像、内部リンク、テスト記事を検査
6. 一時フォルダで本番相当のHugoビルドを実行
7. title、description、canonical、OGP、Twitter Card、JSON-LD、サイト内リンク、sitemap、robots.txt、RSSを生成HTMLで検査
8. 全検査の成功後、正式なPage Bundleへ同期し、指定記事だけをGitへ登録
9. `publish: 記事slug` という記事単位のcommitを作成
10. GitHubへpush
11. 対応するGitHub Actionsの完了を最大10分待つ
12. Actions成功後、公開URLがHTTP 200を返すことを確認

`.gitignore`、仕様書、別の記事など、指定記事以外の変更はcommit対象にしません。

検査結果は `[停止]` と `[警告]` に分かれます。必須情報不足、画像・内部リンク切れ、`review-report.md` 混入、SEOメタ情報の欠落や重複、下書き・新規テスト記事の誤公開は停止します。画像未設定や、過去に意図して公開したnoindex付きテスト記事は警告に留めます。

## 現在のショートカット

- `Alt+Shift+V`: 現在開いているゲームブログ記事を一時領域でプレビュー
- `Alt+Shift+P`: 確認画面の承認後、現在開いているゲームブログ記事を公開
- `Alt+Shift+L`: 確認画面の承認後、既存のlogsブログ（`my-blog`）を公開

## 現在まだ行わないこと

- Discord通知は、今後の実装単位で追加します。
- Obsidianから原稿を削除しても、公開記事は自動削除しません。

## テスト用の実行

`-NoPush` は開発・検証専用です。commitまでは作成するため、通常の手動確認には使わないでください。

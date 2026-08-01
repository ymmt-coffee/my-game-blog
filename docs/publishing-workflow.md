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
draft: true
description: 記事の短い説明
images:
  - images/01.png
---
```

公開する準備ができたら、Obsidian上で `draft: false` に変更します。公開処理は `draft: false` が明示されていない記事を拒否します。

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
4. 指定した1記事だけをPage Bundleへ同期
5. `draft: false` と画像欠落を検査
6. 書き出しなしのHugoビルドを実行
7. 指定記事だけをGitへ登録
8. `publish: 記事slug` という記事単位のcommitを作成
9. GitHubへpush
10. 対応するGitHub Actionsの完了を最大10分待つ
11. Actions成功後、公開URLがHTTP 200を返すことを確認

`.gitignore`、仕様書、別の記事など、指定記事以外の変更はcommit対象にしません。

## 現在のショートカット

- `Alt+Shift+V`: 現在開いているゲームブログ記事を一時領域でプレビュー
- `Alt+Shift+P`: 確認画面の承認後、現在開いているゲームブログ記事を公開
- `Alt+Shift+L`: 確認画面の承認後、既存のlogsブログ（`my-blog`）を公開
- `Alt+Shift+C`: 既存のClaude Code起動（変更なし）

## 現在まだ行わないこと

- Discord通知は、今後の実装単位で追加します。
- Obsidianから原稿を削除しても、公開記事は自動削除しません。

## テスト用の実行

`-NoPush` は開発・検証専用です。commitまでは作成するため、通常の手動確認には使わないでください。

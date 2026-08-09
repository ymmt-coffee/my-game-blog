# 記事更新の暫定手順

## 現在の位置づけ

管理画面はまだ未実装である。この文書は、管理画面からの記事公開が完成するまで、現在の安全なブログ更新機能を維持するための暫定手順である。

管理画面完成後は、保存、校正、プレビュー、公開前チェック、投稿を画面上の操作へ置き換える。Discord通知は使用しない。

## 原稿

現在は `Life_and_Div/30_Projects/01_blog/<記事slug>/` のPage Bundleを原稿として扱う。

```text
<記事slug>/
├─ index.md
├─ review-report.md
└─ images/
```

- 公開本文は `index.md`。
- 校正記録は `review-report.md`。公開対象へ含めない。
- 画像は記事ごとの `images/` に置く。
- 執筆中は `draft: true`、公開時だけ明示的に `draft: false` とする。

## 記事種類

- `play_note`: プレイ途中記。`play_time` が必須。
- `weekly_picks`: 新作・セール5選。未プレイ情報記事として表示する。
- `monthly_essay`: 月次レビューエッセイ。

## 校正

```powershell
.\review.ps1 -Article <記事slug> -Gemini
```

校正は本文を自動修正しない。指摘を確認し、採用する内容だけ人が本文へ反映する。APIキーは環境変数からだけ読み、値を表示しない。

## プレビュー

```powershell
.\preview.ps1 -Article <記事slug>
```

必須項目、画像、内部リンク、秘密情報を検査してからローカルHugoサーバーを起動する。

## 公開

```powershell
.\publish.ps1 -Article <記事slug> -Approve
```

公開処理は校正状態、front matter、画像、リンク、Hugo本番ビルドを検査し、対象記事だけをcommit・pushする。GitHub Pagesの成功と公開URLのHTTP 200を確認する。commitとpushを伴うため、実行前に毎回ユーザー承認を得る。

## 管理画面への移行

新しい管理画面は、上記処理をそのままシェル実行するだけでなく、保存・検査・公開を独立した安全な機能として呼び出す。管理画面完成まではこの暫定経路を削除しない。

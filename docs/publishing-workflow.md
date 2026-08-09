# 記事の校正・プレビュー・公開手順

## 現在の位置づけ

Phase Eの完成後は、通常の記事操作をローカル管理画面で行う。この文書は管理画面の操作手順と、移行前原稿に限る従来経路を示す。

Discord通知は使用しない。

## 管理画面での通常手順

1. デスクトップの「ゲームブログ管理」を開き、記事を選ぶ。
2. 記事を確定保存する。
3. 「AI校正を実行」を押し、指摘ごとに「採用する」または「見送る」を選ぶ。採用を選んでも本文は自動変更されないため、必要な修正は編集欄へ反映して再校正する。
4. 「プレビューを作成」で表示を確認する。
5. 「公開前チェック」を押す。
6. 合格画面で対象、公開先、警告、原稿ハッシュを確認し、対象slugを入力して「投稿を実行」を押す。
7. Pages完了画面を確認する。

公開前チェックの承認は15分間、一回だけ有効である。検査後に原稿が変わった場合は再検査する。

## 原稿

管理画面の記事は `content/articles/<記事slug>/` のPage Bundleを正本として扱う。移行していない外部原稿だけは `Life_and_Div/30_Projects/01_blog/<記事slug>/` に保持する。

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
.\tools\publishing\review.ps1 -Article <記事slug> -Gemini
```

校正は本文を自動修正しない。指摘を確認し、採用する内容だけ人が本文へ反映する。APIキーは環境変数からだけ読み、値を表示しない。

## プレビュー

```powershell
.\tools\publishing\preview.ps1 -Article <記事slug>
```

必須項目、画像、内部リンク、秘密情報を検査してからローカルHugoサーバーを起動する。

## 公開

```powershell
.\tools\publishing\publish.ps1 -Article <記事slug> -Approve
```

公開処理は校正状態、front matter、画像、リンク、Hugo本番ビルドを検査し、対象記事だけをcommit・pushする。GitHub Pagesの成功と公開URLのHTTP 200を確認する。commitとpushを伴うため、実行前に毎回ユーザー承認を得る。

## 移行前原稿の暫定経路

外部Obsidian原稿をまだ管理画面へ移行していない場合だけ、上記PowerShell手順を使用する。外部原稿の移行と削除は別途承認が必要であり、従来経路は移行完了まで削除しない。

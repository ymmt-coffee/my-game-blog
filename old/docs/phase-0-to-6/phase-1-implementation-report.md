# Phase 1「記事形式とHugo基盤」実装結果

- 実施日: 2026-08-02（Asia/Tokyo）
- 対象: `my-game-blog`
- 状態: 完了、commit・push・GitHub Actions・GitHub Pages公開確認済み
- Hugo: `v0.163.2 extended`
- PaperMod: Git submodule commit `154d006e0182dfc7da38008323976b02e6bfab4a`（submodule内は未変更）

## 1. 実装した内容

### 記事形式

3種類のHugo archetypeを追加した。

| kind | 用途 | 主な固有項目 |
|---|---|---|
| `play-note` | 週次のプレイ途中記 | `article_type: play_note`、`play_time` |
| `weekly-picks` | 週次の新作・セール5選 | `article_type: weekly_picks` |
| `monthly-essay` | 月次レビューエッセイ | `article_type: monthly_essay` |

共通項目は `title`、`date`、`lastmod`、`draft`、`description`、`images`、`article_type`、`author` に絞った。必要な場合だけ `spoiler_warning`、`provided`、`corrections` を使う。

### 記事上の表示

- プレイ途中記はプレイ時間と「完走レビューではない」旨を冒頭へ自動表示する
- 新作・セール5選は「未プレイ作品の紹介でありレビューではない」旨を自動表示する
- ネタバレ警告は警告文がある場合だけ表示する
- 提供表示は `provided: true` の場合だけ表示する
- 月次エッセイは、ネタバレまたは提供がない限り定型枠を出さず本文を優先する
- `corrections` がある場合だけ訂正・更新履歴を記事末尾へ表示する

### SEOとサイト出力

- 仮称 `game logs` は変更せず、サイトdescriptionと著者「やまもと」を設定した
- PaperMod既定のtitle、canonical、OGP、Twitter Card、JSON-LDを利用する
- `images` の1枚目を記事のOGP画像として利用する
- 公開日と更新日は `date` と `lastmod` から出力する
- `enableRobotsTXT` を有効化し、PaperMod既定のrobots.txtへsitemap URLを出す
- sitemap、robots.txt、RSSの生成を検査対象にした
- Umami、GA4、PlausibleはID・domainを空のまま保持し、providerを空にして明示的に無効化した

### 画像処理

- Obsidian原本と同期先の元画像は上書き・削除しない
- JPEG、PNG、WebPから幅480、720、1080、1440px以下のレスポンシブ画像を生成する
- 最大表示幅は1440px、WebP品質は82とした
- 透過PNGはWebPを優先配信しつつ、PNGのフォールバックを残す
- GIFはアニメーションを守るため変換せず、幅・高さだけを出す
- SVGとAVIFはそのまま配信する
- 変換物はHugoの生成領域だけに作るため、再実行で原稿やGit管理対象に差分を作らない
- 画像なしの記事はOGP画像なし・summary形式のTwitter Cardへ安全にフォールバックする

### 公開前検査

`scripts/validate_blog.py` を追加し、プレビューと公開処理へ接続した。

公開を停止する項目:

- 必須front matter不足、型の誤り、記事種別固有項目不足
- 参照画像の欠落、未対応形式、記事外への危険な参照
- 壊れた相対内部リンク、生成後の壊れたサイト内リンク
- `review-report.md` の公開用content混入
- canonical、主要OGP、Twitter Card、JSON-LDの欠落・重複・不正
- sitemap、robots.txt、RSSの欠落
- `draft: false` ではない公開対象
- 明示許可のないテスト用コンテンツの `draft: false`

警告に留める項目:

- 画像未設定
- 文章、構成、SEOの改善提案
- Phase 0で意図して公開済みのnoindex付きテスト記事2件

公開処理はまず一時フォルダへ同期して本番相当ビルドを行い、生成HTMLの検査に成功してから正式なPage Bundleへ同期し、対象記事だけをstageする。検査失敗時は正式な `content/posts/` を変更しない。既存のcommit対象限定、push後のActions確認、公開URL確認は維持した。

### 固定ページ

- About
- プライバシーポリシー
- 広告・アフィリエイト方針
- 提供作品・レビューキー方針

正式名、独自ドメイン、専用メール、広告事業者は作成せず、「仮称」「準備中」「未導入」と明記した。

## 2. テスト結果

### 変更前

- Git: `main`、`origin/main`、作業ツリーはクリーン
- PaperMod submodule: 正常、固定commitから変更なし
- Hugo本番相当ビルド: 成功
- 既存同期テスト: 4件成功
- 公開承認なしの実行: 正しく停止

### 変更後

- 自動テスト: 9件すべて成功
  - 既存同期テスト4件
  - front matter・画像・内部リンク・テスト記事の異常検出4件
  - 3記事種別、SEO、画像最適化、下書き除外、主要生成物の統合テスト1件
- Python構文検査: 成功
- `preview.ps1`、`publish.ps1` のPowerShell構文検査: 成功
- Hugo 0.163.2 extendedの本番相当ビルド: 成功
- 実コンテンツの生成HTML検査: 停止0件、警告2件
- sitemap、robots.txt、RSS: 生成を確認
- title、description、canonical、OGP、Twitter Card、JSON-LD: 検査成功
- 解析タグ: Umami、GA4、Plausibleすべて出力0件
- 一時テストの下書き記事: 本番生成物に含まれないことを確認
- `review-report.md`: 既存同期テストで生成サイトに含まれないことを確認
- 大型PNG: 1440pxへ縮小し、複数幅PNGとWebP、幅・高さを出すことを確認
- 実装commit: `f8a566a38f75eda93ee3ce5905090b4ddc0b645a`
- GitHub Actions: build・deploy成功
- 公開確認: トップ、4固定ページ、robots.txt、sitemap、RSSがHTTP 200
- 公開トップ: サイトdescriptionと固定ページメニューを確認
- 公開トップ: Umami、GA4、Plausibleの解析タグが出ていないことを確認

## 3. 非推奨警告

- `languageCode`: プロジェクト設定を `locale = "ja-JP"` へ移行して解消
- `.Language.LanguageDirection`: プロジェクト側の小さな基底テンプレート上書きで `.Language.Direction` へ移行して解消
- `.Language.LanguageCode`: PaperMod submoduleのOGPテンプレート由来で1件残る。テーマ内を直接変更する制約を優先し、無理に改変していない

## 4. 既存機能への影響

- Obsidian原稿は読み取りも書き換えもしていない
- 既存公開記事は削除していない
- Page Bundle同期、画像欠落停止、`review-report.md`除外、`draft: false`公開ゲートを維持した
- `Alt+Shift+V` と `Alt+Shift+P` の役割を維持し、両方へ新検査を追加した
- `Alt+Shift+L` と独立した`my-blog`の処理は変更していない
- Claude Code用ショートカットは復活させていない
- PaperMod submodule内は変更していない
- APIキー、Webhook URL、解析ID、トークンは追加していない
- 外部サービス設定は変更していない

## 5. 保留・ユーザー判断が必要な事項

1. 正式なブログ名、独自ドメイン、専用メール、広告事業者は未決定のまま
2. 既存の公開フローテスト記事2件は、削除禁止を優先して公開状態のまま維持している。いずれも `robotsNoIndex: true` であり、検査時に警告する。将来、残す・下書き化する・削除するかはユーザー判断が必要
3. PaperMod由来の `.Language.LanguageCode` 警告1件は、将来のテーマ更新または上流対応時に再確認する

GitHub Actionsには、利用中のGitHub公式ActionがNode.js 20から24へ移行中である旨の警告が出た。build・deployは成功しており、Phase 1の公開を妨げるものではない。将来、公式Actionの新しいメジャーバージョンが安定した時点で更新を検討する。

## 6. 判定

Phase 1は実装、ローカル検証、commit、push、GitHub Actions、公開URL確認まで完了した。Phase 2へ進める状態である。

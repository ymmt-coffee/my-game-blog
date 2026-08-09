# Phase 0「現状監査」結果

- 監査日: 2026-08-01（Asia/Tokyo）
- 対象: `my-game-blog`
- 監査方針: 読み取りと非破壊確認のみ。commit、push、公開、同期スクリプト実行、外部設定変更は未実施
- 正本資料: `docs/blog_automation_spec.md`、`docs/roadmap.md`、`data/editorial/strategy.yaml`、`docs/game-blog-operation-plan.html`

> 監査後の整理（2026-08-02）: `blog_automation_spec.md` と `roadmap.md` はリポジトリ直下から `docs/` へ移動した。本書内のディレクトリ構成とGit状態は、特記がない限り監査時点の記録である。

## 1. エグゼクティブサマリー

現時点で動作しているのは、Hugo + PaperModによる空サイトのローカルビルドと、GitHub ActionsからGitHub Pagesへ公開する基盤である。公開URLは `https://ymmt-coffee.github.io/my-game-blog/` でHTTP 200を返し、2026-08-01の定期デプロイも成功している。sitemapとRSSも配信されている。

一方、Obsidianからこのゲームブログへ記事を安全に公開する一連の運用は動作可能な状態ではない。最大の理由は、Obsidianの `Alt+Shift+P` が本リポジトリではなく旧 `my-blog\publish.ps1` を呼ぶ点である。また、本リポジトリの `publish.ps1` も、同期直後に `git add .`、commit、pushまで実行するため、プレビューと公開承認が分離されておらず、ユーザーの未コミット変更を巻き込む危険がある。

同期スクリプトは旧来の「Markdownファイルを平坦化して `content/posts/` へ置き、画像を `static/images/` へ集約する」方式である。新仕様のPage Bundle、`review-report.md` 非公開、記事単位の `images/`、下書き管理、画像最適化には対応していない。特に現状のまま新仕様フォルダを同期すると、`review-report.md` が通常記事として公開対象になり得る。

結論として、Phase 1の実装へ直ちに進むべき状態ではない。まず公開誤操作とユーザー変更巻き込みを防ぐ安全対策、Hugoバージョン固定、原稿構造と公開承認方式の確定が必要である。監査結果のユーザー確認後にPhase 1へ進むことを推奨する。

### 重大度別件数

| 重大度 | 件数 | 主な内容 |
|---|---:|---|
| Critical | 3 | 未承認公開、未コミット変更の巻き込み、校正レポート誤公開の危険 |
| High | 5 | ショートカットの旧ブログ参照、Page Bundle非対応、同期時衝突、画像欠落でも続行、CIの再現性不足 |
| Medium | 7 | SEO不足、robots.txt欠落、画像最適化なし、解析未設定など |
| Low | 3 | 非推奨設定、固定パス、保守性上の問題 |

## 2. 現在のディレクトリ構成

主要部分は次のとおり。`content/posts/`、`static/images/`、Obsidian原稿の `30_Projects/01_blog/` は監査時点で空だった。

```text
my-game-blog/
├─ .github/workflows/hugo.yml    # Pages用CI/CD
├─ archetypes/default.md         # 新規記事の最小front matter
├─ assets/css/extended/custom.css# Hugo Pipes対象の独自CSS
├─ content/posts/                # 現行同期先（空）
├─ data/editorial/strategy.yaml  # 機械可読な運営仕様
├─ docs/
│  └─ game-blog-operation-plan.html
├─ layouts/                      # PaperModの独自上書き
├─ scripts/sync_diary.py         # Obsidian原稿の同期
├─ static/images/                # 現行画像同期先（空）
├─ themes/PaperMod/              # Git submodule
├─ hugo.toml
├─ publish.ps1
├─ blog_automation_spec.md
└─ roadmap.md
```

### Hugo各ディレクトリの役割と現状

| ディレクトリ | Hugoでの役割 | 現状 |
|---|---|---|
| `content` | 公開ページのMarkdown | `posts/` のみ、記事0件 |
| `assets` | Hugo Pipesで処理するCSS・JS・画像 | 独自CSSのみ。記事画像は置かれていない |
| `static` | 変換せず公開ルートへコピー | `images/` は空。同期画像の出力先 |
| `data` | テンプレートや自動処理から読む構造化データ | 運営戦略YAMLあり。現行Hugoテンプレートからの利用は確認できない |
| `layouts` | テーマテンプレートの上書き | 一覧、日付表示、トップ記事表示、解析タグなど複数の独自実装あり |
| `archetypes` | `hugo new content` の雛形 | `date`、`draft: true`、ファイル名由来の `title` のみ |

`docs/` と `data/` は現在未追跡である。`.gitignore` もユーザーの未コミット変更として存在する。本監査ではこれらを変更・破棄していない。ただし本レポートは指定成果物のため `docs/phase-0-audit.md` として追加した。

## 3. 現在のObsidianから公開までのフロー

### 実際のフロー

```text
Obsidian Alt+Shift+P
  → 旧 my-blog/publish.ps1（本リポジトリではない）

本リポジトリの publish.ps1 を直接実行した場合
  → scripts/sync_diary.py
  → git add .
  → 変更があれば git commit -m "update posts"
  → git push
  → mainへのpushをGitHub Actionsが検知
  → Hugoビルド
  → GitHub Pagesへデプロイ
```

### Obsidian設定

- Vault: `Life_and_Div`
- Shell Commandsプラグイン: 導入済み
- `Alt+Shift+P`: alias `publish` を実行
- 実コマンド: 旧プロジェクト `30_Projects/10_Apps/my-blog/publish.ps1`
- 実行前確認: 無効
- `Alt+Shift+C`: Claude Code起動用であり公開処理ではない

したがって、現在のObsidianショートカットから `my-game-blog` は公開されない。ショートカットを実際に押す試験は、旧ブログの同期・commit・pushを発生させ得るため実施していない。

### `scripts/sync_diary.py` の監査

| 項目 | 現状 |
|---|---|
| 入力元 | Windows絶対パス `Life_and_Div/30_Projects/01_blog` |
| 対象 | 配下の全 `*.md` を再帰取得。除外規則なし |
| 出力先 | `content/posts/<元ファイル名>` |
| 画像出力先 | `static/images/<元画像名>` |
| front matter | `python-frontmatter` で読み書き。titleがなければファイル名、dateがなければ更新日時をJSTで設定 |
| `publish` キー | 常に削除される |
| wikilink | `[[ページ]]` は文字列へ変換し、リンクとしては保持しない |
| Obsidian画像 | `![[画像名|代替文]]` をMarkdown画像へ変換 |
| 画像検索 | 原稿の同階層・祖先階層、および各 `attachments/` を探索 |
| 削除同期 | 前回同期済み一覧から消えたMarkdownに対応する出力記事を削除 |
| 状態ファイル | `scripts/.synced_files.json`（gitignore済み） |

### 重要な挙動

1. ディレクトリ構造を捨て、出力をファイル名だけに平坦化する。同名Markdownが複数フォルダにあると同じ出力を順番に上書きし、警告しない。
2. 新仕様の `article-name/index.md` はすべて `content/posts/index.md` に集約され、複数記事を正しく扱えない。
3. `review-report.md` も除外されず、`content/posts/review-report.md` へ同期される。front matterに `draft` がなければ公開される可能性がある。
4. `draft` の自動付与や公開承認状態の検査はない。既存の `draft` キーは保持するが、下書き・公開の運用規則は実装されていない。
5. `publish` キーは無条件削除されるため、これを承認フラグとして利用できない。
6. 画像は記事単位でなく全記事共通の `/images/` に集約される。同名画像は、既存出力より元画像の更新日時が新しい場合だけ上書きされ、異なる記事間で衝突し得る。
7. 画像が見つからなくても警告して代替文だけを残し、同期処理全体は成功扱いになる。仕様上の「必須画像欠落時は公開停止」を満たさない。
8. 圧縮、WebP化、寸法変換、Hugo Image Processingはない。
9. 元原稿を変更・削除する処理はないが、前回同期済みの公開記事を削除する処理はある。
10. 同期状態が壊れた場合は空状態として継続するため、削除対応の信頼性が下がる。

### `publish.ps1` の監査

- 各外部コマンドの終了コードを確認し、失敗時は後続処理を止める基本的なエラー処理はある。
- 同期 → `git add .` → commit → pushの4段階で、ローカルビルド、プレビュー、公開承認、デプロイ結果確認はない。
- `git add .` は記事以外も含む全変更を登録する。監査時点の `.gitignore`、`data/`、`docs/` のようなユーザー変更も巻き込む。
- commitメッセージは常に `update posts` で、記事単位の履歴にならない。
- push後のActions成功を待たずに「完了」と表示する。
- 再実行時、同期結果に差分がなければcommitはスキップされる点は部分的に冪等。ただし画像名衝突、削除同期、既存変更の巻き込み、外部通知の重複防止は未解決。
- ローカルプレビューと公開処理は分離されていない。

## 4. Hugoとテーマの監査結果

### 基本設定

| 項目 | 現状 | 評価 |
|---|---|---|
| `baseURL` | `https://ymmt-coffee.github.io/my-game-blog/` | 現公開URLと一致 |
| 言語 | `languageCode = "ja"` | 意図は正しいがHugo 0.158以降で非推奨。`locale` への移行が必要 |
| タイトル | `game logs` | 仕様どおり仮名称 |
| テーマ | `PaperMod` | Git submoduleで導入 |
| `buildFuture` | `false` | 未来日記事は定期ビルド時に公開されない |
| front matter日付 | `date`、`publishDate` | 両方を公開日候補として読む |

### バージョンと導入方式

- ローカルHugo: `v0.163.2+extended`
- 公開HTMLのgenerator: `Hugo 0.164.0`
- Actions: `peaceiris/actions-hugo@v3` + `hugo-version: latest` + extended
- PaperMod: submodule commit `154d006e...`、`v8.0-138-g154d006`
- PaperModはcommitで固定されているが、HugoはActionsで固定されていない。監査時点でもローカルとCIに差がある。

### 独自上書き

- `layouts/list.html`: ホーム・一覧の表示を独自化
- `layouts/_partials/home_featured.html`: 最新記事を大きく表示
- `layouts/_partials/home_archive_entry.html`: 過去記事を簡潔に表示
- `layouts/_partials/post_entry.html`、`post_meta.html`、`post_summary.html`: 記事一覧の表示上書き
- 日付・経過時間関連の複数partial: 日本語の日付表示を追加
- `layouts/_partials/extend_head.html`: Google Fontsと独自解析partialを挿入
- `layouts/_partials/analytics*.html`: Umami、GA、Plausibleの切替実装
- `assets/css/extended/custom.css`: フォント、ヘッダー、最新記事・過去記事表示を上書き

これらはPaperMod内部partial名に依存するため、テーマ更新時に互換性監査が必要である。

### front matterと記事形式

archetypeは `date`、`draft = true`、`title` のみ。新仕様に必要となるdescription、画像、記事種別、プレイ時間、公開承認、提供表示、訂正履歴等はない。現行同期スクリプトはarchetypeを使用せず、入力原稿のfront matterを補完する。

### SEO・メタ情報

- title: PaperModにより出力。公開トップは `game logs`
- canonical: PaperModにより出力。公開トップでbaseURLと一致を確認
- OGP: PaperModにより基本タグを出力。公開トップの `og:title` を確認
- 構造化データ: PaperModによりJSON-LDを1件出力
- description: `hugo.toml` にサイトdescriptionがなく、公開トップでもmeta descriptionなし
- 記事ごとのdescription、OGP画像: 記事がなく確認不能。運用ルールも未実装
- sitemap: `/my-game-blog/sitemap.xml` がHTTP 200
- RSS: `/my-game-blog/index.xml` がHTTP 200
- robots.txt: `/my-game-blog/robots.txt` はHTTP 404
- canonical、OGP、構造化データは主にPaperMod既定実装へ依存し、独自要件に対するテストはない

### 画像処理

Hugo Image Processingは使用されていない。同期画像は `static/images` へ原形式・原サイズでコピーされるため、圧縮、WebP化、responsive image、幅高さ属性生成はない。監査ビルドのProcessed imagesは0件だった。

### ローカルビルド

`hugo --renderToMemory --minify` は成功した。記事0件でPages 8、Static files 0、Processed images 0。Hugoの言語関連プロパティに非推奨警告が出るが、現時点ではビルドを止めない。`python-frontmatter` もローカルPython 3.14.4からimportできる。

## 5. GitHub Actionsと公開先の監査結果

### Git状態

- remote: `origin https://github.com/ymmt-coffee/my-game-blog.git`
- current branch: `main`
- upstream: `origin/main`
- submodule: `themes/PaperMod`、正常にcommit固定
- 監査開始時の作業ツリー: `.gitignore` 変更、`data/` 未追跡、`docs/` 未追跡
- 上記はユーザー変更として維持。commit、stage、push、巻き戻しは未実施

### Workflow

| 項目 | 現状 |
|---|---|
| push | `main` へのpushで実行 |
| schedule | `0 23 * * *`。UTC基準で通常JST 08:00 |
| 手動実行 | `workflow_dispatch` がなく不可 |
| checkout | submoduleあり、全履歴取得 |
| build | Hugo extendedの `latest` で `hugo --minify` |
| artifact | `public/` をPages artifactとして登録 |
| deploy | `actions/deploy-pages@v4`、`github-pages` environmentへ公開 |

GitHub ActionsのcronはUTCであり、日本は夏時間を採用しないためJST 08:00で一定。日次ビルドは未来日コンテンツを時刻到来後に公開する用途には使えるが、現在は `buildFuture = false` であり、日時指定の精度はfront matterとHugoの判定に依存する。

### 実稼働確認

- Pages build type: workflow
- public: true
- HTTPS enforced: true
- custom domain: なし
- Pages URL: `https://ymmt-coffee.github.io/my-game-blog/`
- トップページ: HTTP 200、タイトル `game logs`
- 直近のPages workflow: 2026-08-01 00:06 UTC開始、schedule、success
- 直前のscheduleおよび初回pushデプロイもsuccess

### 失敗時と再実行安全性

- build失敗時はdeploy jobが `needs: build` のため実行されず、既存公開サイトは通常そのまま残る。
- deploy失敗はActions上で失敗になるが、Discord等への通知はない。
- publish.ps1はデプロイ結果を確認しないため、ローカルでは成功表示のまま公開失敗を検知できない。
- Workflow自体は同一commitを再ビルドして同一artifactを再配置する構造で、概ね再実行可能。ただしバージョンが `latest` のため、同一commitでも実行時期により出力や成否が変わり得る。
- concurrency制御がないため、短時間に複数push/scheduleが重なると旧runが後からdeployする競合可能性を排除できない。

## 6. SEO・アクセス解析の現状

| 項目 | 現状 | 評価 |
|---|---|---|
| title | 仮タイトルを出力 | 一部実装 |
| description | 未設定 | 未実装 |
| canonical | PaperMod既定で出力、baseURL整合 | 実装済み（既定機能） |
| OGP | PaperMod既定の基本タグ | 一部実装 |
| 構造化データ | PaperMod既定のJSON-LD | 一部実装 |
| sitemap | 配信中 | 実装済み |
| RSS | 配信中 | 実装済み |
| robots.txt | 404 | 未実装 |
| Umami | providerはumamiだがwebsiteId空。partialは空IDなら出力しない | 未実装 |
| GA4 | measurementId空、providerもgoogleではない | 未実装 |
| Plausible | domain空、provider対象外 | 未実装 |
| Search Console | 所有権確認タグ・設定・sitemap送信の証拠なし | 確認不能／未実装相当 |

公開ページは本文記事が0件で、トップのmeta descriptionもない。Phase 1ではサイトdescription、記事description、OGP画像、robots.txt、Search Console所有権確認方式、GA4の同意・プライバシー表記を合わせて設計する必要がある。

## 7. セキュリティと秘密情報管理の確認結果

### 確認結果

- Git管理対象に対して、代表的な秘密鍵・GitHub token・AWS access key・Discord webhook・Google API key形式を値を表示せず検査した範囲では一致なし。
- `.env`、secret、credential、token、秘密鍵形式を示す疑わしい追跡ファイル名も検出なし。
- `hugo.toml` の解析IDは空で、正本資料にも実値はない。
- GitHub CLI認証はOSのkeyringを使用しており、リポジトリ内に保存された証拠はない。

これは限定的なパターン検査であり、「秘密情報が絶対にない」ことの保証ではない。Git履歴全体に対する専用secret scanner、GitHub上のSecrets設定値、Pages environment保護規則は本監査では確認していない。

### セキュリティ上の問題

- `publish.ps1` の `git add .` は、将来誤って置かれた秘密ファイルも含めてstageする危険がある。
- Obsidian公開ショートカットは確認ダイアログなしで旧ブログのcommit/pushまで到達し得る。
- GitHub Actionsの依存アクションはmajor tag指定でcommit SHA固定ではない。個人ブログとして一般的な設定ではあるが、サプライチェーン厳格化の余地がある。
- Discord、SNS、Google Drive等の秘密情報管理は未実装であり、漏洩は確認されていない。

## 8. 仕様に対する実装状況一覧

| 項目 | 評価 | 根拠・差分 |
|---|---|---|
| 記事のPage Bundle化 | 既存実装の修正が必要 | 現行は全Markdownを `content/posts/<filename>` に平坦化し、画像を共通staticへ置く |
| `review-report.md` | 既存実装の修正が必要 | 除外されず公開対象へ同期され得る |
| AI校正 | 未実装 | 校正処理・レポート生成・分類・証跡管理なし |
| 最終プレビューと明示的な公開承認 | 既存実装の修正が必要 | publish.ps1が同期からpushまで連続実行。ローカルビルドも承認確認もない |
| Discord通知 | 未実装 | Workflow・スクリプトともWebhook処理なし |
| Google Driveバックアップ | 未実装 | 容量監査、日次処理、月次snapshot、通知なし |
| 新作・セール記事 | 未実装 | 調査・生成・期限・予約公開処理なし |
| AI編集長 | 未実装 | 候補選定、台帳、Obsidian選択、定期実行なし |
| SNS投稿 | 未実装 | X/Bluesky連携、承認、予約、重複防止なし |
| GA4 | 未実装 | テンプレートのみ存在しID空・provider未選択 |
| Search Console | 確認不能 | リポジトリに確認タグ等なし。Google側設定はローカルから確認不能 |
| 月次レポート | 未実装 | データ取得・集計・Obsidian保存・Discord要約なし |
| 問い合わせフォーム | 未実装 | 固定ページ・フォームサービス・spam対策なし |
| 広告・アフィリエイト | 未実装 | 方針のみ。表示・リンク管理・開示ページなし |
| 費用上限管理 | 未実装 | 利用額集計、80%警告、停止順制御なし |

補足: Hugo/Pages公開基盤、sitemap、RSS、解析タグを差し込むテンプレート枠は実装済み。ただし指定された運営自動化項目そのものはほぼ実装前であり、正本資料の `status: agreed`、ロードマップの「実装開始前」と整合する。

## 9. 問題点とリスク

### Critical

| ID | 問題 | 影響 |
|---|---|---|
| C-1 | 公開前プレビューと明示承認がなく、publish.ps1がpushまで連続実行 | 下書き・誤内容を公開する危険 |
| C-2 | `git add .` が作業ツリー全体を対象にする | ユーザーの未コミット変更や秘密ファイルを意図せずcommit/pushする危険 |
| C-3 | `review-report.md` を同期対象から除外しない | AI校正記録や内部メモを外部公開する危険 |

### High

| ID | 問題 | 影響 |
|---|---|---|
| H-1 | Obsidianショートカットが旧 `my-blog` を参照 | ゲームブログを公開できず、別ブログを誤更新する可能性 |
| H-2 | Page Bundleと記事別imagesに非対応 | 新仕様の記事を複数扱うと `index.md` が衝突し、記事構造が壊れる |
| H-3 | ファイル名平坦化と画像名共通化 | 同名ファイルを無警告で上書きし、記事・画像を取り違える可能性 |
| H-4 | 画像欠落が警告のみで成功終了 | 壊れた記事をcommit/pushできる |
| H-5 | ActionsのHugoが `latest` | ローカル再現不能、同一commitでも将来ビルド結果が変わる |

### Medium

| ID | 問題 | 影響 |
|---|---|---|
| M-1 | deploy成功をpublish.ps1が確認しない | 実際は未公開でも完了と誤認する |
| M-2 | concurrency制御なし | 複数runが競合する可能性 |
| M-3 | site/article descriptionとOGP画像運用なし | 検索・SNS表示品質が低い |
| M-4 | robots.txt 404 | crawler方針とsitemap URLを明示できない |
| M-5 | 画像圧縮・WebP・responsive処理なし | 表示速度と転送量に悪影響 |
| M-6 | GA4・Search Console未接続 | 成果計測と月次改善ができない |
| M-7 | 固定commitメッセージ | 記事単位の追跡・訂正履歴要件を満たさない |

### Low

| ID | 問題 | 影響 |
|---|---|---|
| L-1 | `languageCode` とPaperMod側言語APIに非推奨警告 | 将来Hugoでビルド不能になる可能性 |
| L-2 | 同期元がユーザー名を含む絶対パス | PC移行・別環境で動かない |
| L-3 | 独自layoutがPaperMod内部partialに密結合 | テーマ更新時の保守負担 |

## 10. Phase 1以降へ進む前に必要な対応

1. 本監査結果をユーザーが確認し、下記「確認が必要な事項」を決定する。
2. Obsidianの旧ブログ用ショートカットは、Phase 1の安全な公開処理が完成するまで本リポジトリへ単純に付け替えない。
3. 公開処理を「校正」「一時同期・プレビュー」「明示承認後の正式同期・push」に分離する設計を確定する。
4. `git add .` を廃止し、公開対象記事と必要画像だけを検証後にstageする方針を確定する。
5. Page Bundleの変換規則、slug/フォルダ名、一意性、`review-report.md` 除外を確定する。
6. 同期時の削除を自動で許可するか、削除候補提示と承認を必要とするか決める。
7. ローカルとActionsで同じHugo extendedバージョンを固定する。
8. 欠落画像、必須front matter、Hugoビルド失敗をpush前に停止条件として実装する。
9. Phase 1でGA4/Search Consoleを導入する場合、ブログ専用Googleアカウントとプライバシー表記方針を用意する。
10. `.gitignore` の既存ユーザー変更を基準として保護し、仕様書類をGit管理するかローカル専用とするか決める。

## 11. 推奨する実装順

1. **安全柵**: dry-run、対象限定stage、削除保護、秘密ファイル検査、公開処理の停止条件
2. **記事モデル**: Page Bundle、`index.md`、記事別 `images/`、`review-report.md` 完全除外、front matter schema
3. **プレビューと承認分離**: 一時出力先でのpreviewと、別操作によるpublish
4. **再現可能ビルド**: Hugo固定、ローカル事前ビルド、Actions concurrency、deploy結果確認
5. **Hugo/SEO基盤**: description、canonical検査、OGP画像、robots.txt、構造化データ、画像最適化
6. **Obsidian接続**: 安全な新コマンド完成後にのみショートカットを付け替え
7. **解析**: GA4、Search Console、プライバシー表記、計測確認
8. **通知**: Discordのエラー・公開結果通知
9. **バックアップ**: 容量確認後にGoogle Drive日次・月次snapshot
10. **コンテンツ自動化**: 新作・セール記事、AI校正、AI編集長
11. **外部配信・分析**: SNS予約・重複防止、月次レポート
12. **収益機能**: 問い合わせ、アフィリエイト、広告、費用上限制御

Phase 1の中でも、SEOや解析より先に誤公開・データ衝突・ユーザー変更巻き込みを防ぐ実装を置くべきである。

## 12. ユーザーへ確認が必要な事項

1. **公開承認の操作**: Obsidian内の別ショートカット、PowerShellの確認画面、Codex上の承認のどれを正とするか。
2. **原稿の公開状態**: `draft`、`status`、`publish` のどのfront matterを使い、どの値を明示承認とみなすか。
3. **記事URL**: Page Bundleのフォルダ名をそのままslugにするか、front matterの `slug` を必須にするか。
4. **同期削除**: Obsidianから原稿が消えたとき、Hugo記事も自動削除してよいか、毎回確認するか、原則残すか。
5. **既存 `my-blog` との関係**: 旧ブログの `Alt+Shift+P` を残し、ゲームブログ用に別キーを追加するか、置き換えるか。
6. **仕様書類のGit管理**: 現在gitignore対象の `docs/blog_automation_spec.md`、`docs/roadmap.md` と、未追跡の `data/`、`docs/` を今後リポジトリで共有・履歴管理するか。
7. **ブログ名・独自ドメイン**: Phase 1では仮の `game logs` とGitHub Pages URLのままSEOを整備してよいか。
8. **解析サービス**: Phase 1でGA4を優先し、現在テンプレートだけあるUmami/Plausibleは無効のまま残すか、整理するか。
9. **Search Console**: ブログ専用Googleアカウントは作成済みか。未作成ならPhase 1のどの時点で用意するか。
10. **公開対象の最低front matter**: title、date、description、article type、images以外に、プレイ時間・提供表示・ネタバレ警告を必須化するか。

## 正本資料間の矛盾・曖昧さ

勝手に解決せず、推奨案を併記する。

| 箇所 | 差分 | 推奨案 |
|---|---|---|
| 正本の優先順位 | 詳細仕様は「意図は仕様書で確認し、確定値はstrategy.yaml」とする一方、4資料すべてを同期対象としている | 数値・真偽・列挙はYAML、文章上の意味と禁止事項は仕様書、実装順はroadmapと明文化する |
| コンテンツの正本 | HTMLは「GitHubを記事・企画・分析記録の正本」と記載。仕様書/YAMLは原稿sourceをObsidianとする | 記事本文の正本はObsidian、公開物と自動処理・履歴の正本はGitHub、と責任範囲を分けて4資料を修正する |
| 公開承認 | 仕様書/YAMLはローカルプレビュー後の「別操作」を必須とする。HTMLのSNS図には「Discord承認または自動予約」とあり、記事公開承認との区別が曖昧 | 記事公開承認はローカルの別操作で必須、Discord承認はSNS等の将来機能に限定すると明記する |
| Phase表記 | roadmapはPhase 0監査から始まるが、HTMLは「PHASE 1 / NOW」を公開基盤整備として表示 | HTMLにもPhase 0監査を追加するか、「Phase 0完了後のNow」と表記する |
| 画像形式 | 仕様書の例は `.png`、HTMLの例は `.webp`。本文は必要に応じてWebP化とする | Obsidian原本はpng等を許可し、Hugo同期先で生成物をWebP化すると明記する |
| Gitの位置づけ | HTMLはGitHubを正本とするが、仕様書はObsidian本文をAIが変更しないことを重視 | GitHub側の生成記事を手編集禁止とし、本文変更はObsidianへ戻す一方向同期を採用する |

## 監査上の制約

- 原稿フォルダが空のため、実在原稿を用いた変換結果、front matterの実例、画像探索の実例は確認不能。
- Obsidianショートカットの実行は、旧ブログをcommit/pushし得るため未実施。設定ファイルから呼出先を確認した。
- 同期スクリプトは出力・削除・状態ファイル更新を行うため未実行。コード、依存関係、入出力パスを静的監査した。
- GitHub Pagesの外部表示、HTTP配信、Actions/Pagesメタデータは2026-08-01時点で確認した。将来の稼働を保証するものではない。
- Search Console、GA4、Discord、Google Drive等の外部アカウント設定はリポジトリから確認できず、変更もしていない。

## Phase 0判定

**条件付き完了**。現行フロー、Hugo、Obsidian設定、Git/Pages、公開URL、仕様差分は監査できた。ただしロードマップの「既存ショートカットを使ったテスト原稿の同期結果」は、安全制約と誤った呼出先、空の原稿フォルダにより実行していない。静的監査により、実行すれば旧ブログを公開し得ることが判明したため、テスト実行より停止・報告を優先した。

監査結果の確認とユーザー判断が終わるまで、Phase 1の実装を開始しないこと。

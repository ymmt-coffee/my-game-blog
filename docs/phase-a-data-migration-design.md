# Phase A データ構造・移行設計

作成日: 2026-08-09
状態: ユーザー承認済み・Phase A完了
対象: Phase Aのみ。管理画面本体、依存追加、原稿移動、外部設定変更は行わない。

## 1. 結論

推奨する正本は、リポジトリ内に新設する `content/articles/<slug>/` である。記事本文と画像を通常のファイルで保存し、SQLiteは状態、予定、履歴、エラーなどの「管理台帳」に限定する。

```text
my-game-blog/
├─ content/articles/<slug>/       # 原稿の正本（Git管理）
│  ├─ index.md
│  └─ images/
├─ blog/content/posts/<slug>/     # 公開用Hugoコピー（正本ではない）
└─ var/admin/                     # 非公開・Git管理外
   ├─ admin.sqlite3
   ├─ autosave/<article-id>/
   ├─ history/<article-id>/
   ├─ reviews/<article-id>/
   ├─ migrations/
   └─ logs/
```

この構成なら、管理画面やSQLiteが壊れても `index.md` と画像を直接読める。Hugoへ渡す前に公開用コピーを作るため、校正レポート、自動保存、履歴、エラー記録がWebへ混入しにくい。リポジトリ全体と外部原稿フォルダは現在の日次・月次バックアップ対象なので、保存範囲の追加変更も不要である。

Phase Cで安全な移行機能を実装し、記事ごとの移行承認を得るまでは、現在の外部原稿 `Life_and_Div/30_Projects/01_blog/` を正本とし、既存のObsidian手順を維持する。現時点では原稿を移動も削除もしない。

## 2. 調査結果

- branch: `main`
- remote: `origin` は `ymmt-coffee/my-game-blog`
- 基準commit: `5c78cba chore: separate blog and operations`
- 作業ツリーとstage: 変更なし
- PaperMod submodule: `154d006...`
- 記事関連テスト: 25件成功
- バックアップ関連テスト: 26件成功
- Hugo v0.163.2 本番相当ビルド: 成功（非推奨警告1件のみ）
- 外部原稿: Page Bundle 3件。`index.md`、記事によって `images/`、`review-report.md`
- 公開側: `blog/content/posts/` に3件。YAMLとTOMLのfront matterが混在し、古いテスト記事には現在の必須項目がない
- GitHub Pages: `main` push、手動、毎朝8時のscheduleでHugoをビルド・公開
- バックアップ: 日次は `Life_and_Div` 全体、月次は外部原稿と本リポジトリを含む。`var/`、一時ファイル、秘密ファイルは除外
- Obsidianショートカット: `tools/publishing/` の校正、プレビュー、公開ランチャーを参照

調査では外部原稿の構造と先頭メタデータだけを読み、本文・画像・設定を変更していない。

## 3. 正本候補の比較

| 候補 | 消失リスク | Hugo | 編集 | 移行 | バックアップ/Git | Obsidian終了後 |
|---|---|---|---|---|---|---|
| `content/articles/` を新設 | 低い。公開用と非公開用を分離 | 同期が1段必要 | 管理画面向けに明確 | 初回移行が必要 | 両方良好 | 最も分かりやすい |
| `blog/content/posts/` | 公開用データと履歴を混ぜやすい | 最も直接的 | 非公開情報の置場に注意 | 公開済み記事は軽い | Gitは良好 | 一見簡単だが公開境界が曖昧 |
| 外部原稿を維持 | 現状と同じ | 現行同期を再利用 | 管理画面から外部パス依存 | 最小 | バックアップ済み、Git外 | Obsidian時代の構造が残る |

`content/articles/` を推奨する理由は、「編集する原稿」と「Webへ出すコピー」の境界が目で見て分かるためである。`admin/` 配下に原稿を置かないのは、アプリ本体と大切なデータを分離するためである。

## 4. ファイル配置

正本の各記事は次のPage Bundleとする。

```text
content/articles/<slug>/
├─ index.md              # 本文と公開に必要なfront matter
└─ images/               # 元画像。追加時は名前衝突を検査し、無断上書きしない
```

記事フォルダへ管理用JSON、SQLite、校正レポート、自動保存を置かない。これらは `var/admin/` に記事IDで分離する。`review-report.md` は移行時に `var/admin/reviews/<article-id>/latest.md` へコピー候補として扱うが、元ファイルは保持し、公開同期から常に除外する。

`blog/content/posts/` は生成可能な公開用コピーであり、管理画面から直接編集しない。同期は対象記事だけを一時ディレクトリで組み立て、検査後に原子的に置換する。

## 5. 記事状態と遷移

| 状態 | 表示名 | 入る条件 | 主な操作 | 次の状態 | 公開可 | エラー時 |
|---|---|---|---|---|---|---|
| `draft` | 下書き | 新規作成、公開後の再編集、差戻し | 編集、保存、校正、プレビュー、アーカイブ | `review_pending` | 不可 | 状態維持、正常版を保持 |
| `review_pending` | 校正待ち | 保存済み本文に校正を依頼 | 校正、指摘確認、編集、差戻し | `draft`, `ready` | 不可 | 状態維持、再試行可能 |
| `ready` | 公開準備完了 | 現在の本文ハッシュで校正・必須検査成功 | プレビュー、公開前検査、予約、公開、編集 | `draft`, `scheduled`, `published` | 確認後可 | 公開停止、状態維持 |
| `scheduled` | 予約済み | `ready` かつ有効な予約日時、明示確認 | 予約解除、再検査、編集 | `ready`, `draft`, `published` | 時刻到来後のみ | 自動公開せず警告。本Phaseでは設計のみ |
| `published` | 公開済み | push、Pages成功、公開URL確認が完了 | 閲覧、再編集、アーカイブ | `draft`, `archived` | 公開済み | 途中失敗は公開履歴に失敗記録、成功扱いにしない |
| `archived` | アーカイブ | 明示確認後に復元可能な保管へ切替 | 閲覧、復元 | 直前状態（原則`draft`） | 不可 | 元位置を維持 |

通常遷移は `draft → review_pending → ready → published`、予約時は `ready → scheduled → published`。どの状態からも無条件に公開させない。編集で本文ハッシュが変われば `draft` に戻し、古い校正結果を無効にする。

front matterの `draft` はHugoの公開スイッチであり、管理画面状態そのものではない。

- `draft`, `review_pending`, `ready`, `scheduled`, `archived`: `draft: true`
- `published`: `draft: false`
- 公開処理の最終段階だけ、承認対象の一時コピーで `draft: false` を用意する
- 状態とfront matterが矛盾した場合は保存済み原稿を勝手に直さず、公開を停止する

## 6. SQLiteスキーマ案

SQLiteは `var/admin/admin.sqlite3` に置く。外部キー、WAL、busy timeoutを有効にし、スキーマ版を管理する。秘密情報と本文・画像本体は保存しない。

```sql
CREATE TABLE schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE articles (
  id TEXT PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE COLLATE NOCASE,
  article_type TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN
    ('draft','review_pending','ready','scheduled','published','archived')),
  source_path TEXT NOT NULL UNIQUE,
  file_hash TEXT NOT NULL,
  last_saved_at TEXT NOT NULL,
  scheduled_at TEXT,
  published_at TEXT,
  last_reviewed_at TEXT,
  reviewed_file_hash TEXT,
  archived_at TEXT,
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE article_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  article_id TEXT NOT NULL REFERENCES articles(id),
  event_type TEXT NOT NULL,
  from_state TEXT,
  to_state TEXT,
  result TEXT NOT NULL CHECK (result IN ('success','warning','failure')),
  file_hash TEXT,
  message_code TEXT,
  safe_message TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE publish_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  article_id TEXT NOT NULL REFERENCES articles(id),
  file_hash TEXT NOT NULL,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  result TEXT NOT NULL CHECK (result IN ('running','success','failure','unknown')),
  commit_sha TEXT,
  pages_run_id TEXT,
  public_url TEXT,
  safe_error_code TEXT
);

CREATE TABLE article_issues (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  article_id TEXT NOT NULL REFERENCES articles(id),
  severity TEXT NOT NULL CHECK (severity IN ('info','warning','error')),
  code TEXT NOT NULL,
  safe_message TEXT NOT NULL,
  resolved_at TEXT,
  created_at TEXT NOT NULL
);
```

予約は初期版で1記事1件なので `articles.scheduled_at` とし、複数予定が必要になった時だけ別表へ移す。履歴の本文スナップショットはSQLite BLOBではなく `var/admin/history/` のファイルに置き、イベント表にはハッシュと操作結果だけを残す。

## 7. ファイルとSQLiteの整合性

| 情報 | 正しい値 |
|---|---|
| 本文、タイトル、概要、日付、画像参照、記事種類、著者 | `index.md` |
| 画像内容 | `images/` のファイル |
| 管理状態、予約、校正対象ハッシュ、処理・公開履歴 | SQLite |
| Hugo公開可否 | SQLite状態、現在ハッシュ、検査結果、承認、公開用front matterの全条件 |
| slug | フォルダ名が正本。SQLiteは索引。front matterに重複保存しない |

読み込み時に実ファイルのSHA-256を計算し、SQLiteの `file_hash` と比較する。不一致なら「外部変更あり」と表示して編集・公開を停止する。利用者が差分を確認し、次のどちらかを明示選択するまで自動同期しない。

1. ファイル側を採用して新しい管理版として取り込む
2. 履歴から別名で復元し、比較後に保存する

SQLiteが失われた場合は、ファイルを読み取り専用で再走査して台帳を再構築できる。公開済み判定や履歴は推測せず「要確認」にし、Git履歴と公開側を人が確認する。

## 8. 保存・履歴・復元

- 編集中は入力後2秒の待ち時間を置き、最後の変更から30秒以内に自動保存する
- 自動保存は正本を置換せず、`var/admin/autosave/<id>/<tab-id>.md` へ原子的に保存する
- 手動保存は正本への確定保存。元のハッシュとrevisionが開いた時点から変わっていない場合だけ実行する
- 保存表示は「未保存」「自動保存中」「自動保存済み」「保存中」「保存済み」「競合・保存停止」を区別する
- 確定保存は同じディレクトリに一時ファイルを作成し、flush、可能ならfsync、再読込とハッシュ確認後に `os.replace` 相当で置換する
- 確定保存前に現在版を履歴へ退避し、30世代か90日の長い方を保持する。削除候補は確認画面を経る
- ブラウザ異常終了後は自動保存と正本の日時・ハッシュを比較し、上書きせず復元候補を表示する
- PC異常終了後に一時ファイルが残っても正本へ自動採用しない
- 同一記事を複数タブで開く場合は、記事IDとrevisionによる楽観ロックを使い、後勝ち上書きを禁止する
- 外部変更検出時は保存停止。自動保存は別タブIDで保持し、比較画面から人が選ぶ
- 履歴復元はまず新しい復元候補を作り、差分確認後に手動保存する。即時上書きしない

画像追加も一時ファイル、形式・サイズ・ファイル名検査、ハッシュ確認、原子的移動の順に行う。同名画像は上書きせず、名前変更か明示置換を求める。

## 9. アーカイブと削除

初期版に削除機能は作らない。`archived` は管理一覧から通常表示を外す論理状態で、正本ファイルはその場に保持する。これによりリンク切れやGitの大量移動を避けられる。復元は状態を原則 `draft` に戻す。

物理移動や完全削除は将来の別Phaseで、対象一覧、リンク検査、バックアップ、明示承認、ごみ箱またはGitによる復元を用意してから検討する。

## 10. 既存記事の移行

移行は専用ツールを後続Phaseで実装し、次の順序を守る。

1. 外部原稿と公開側を読み取り専用スキャンする
2. slug、形式、front matterキー、画像参照、校正レポート、両側のハッシュを一覧化する
3. YAML/TOML解析、必須項目、画像存在、パストラバーサル、秘密情報、slug大文字小文字重複を検査する
4. 外部原稿と公開側が同じslugで異なる場合は自動選択せず、差分を表示する
5. dry-runで作成先、変換内容、警告、除外物を表示し、機械可読なmanifestを `var/admin/migrations/` に保存する
6. 現在の暗号化バックアップの直近成功を確認し、さらに移行対象だけのローカル退避コピーとハッシュ一覧を作る
7. 1記事ずつ承認し、新フォルダへコピーする。移動しない
8. コピー後に本文・画像のSHA-256、件数、参照、Hugo検査を照合する
9. 失敗時は未完成の新規コピーだけを隔離し、元原稿と公開側は変更しない
10. 全記事を管理画面で編集・校正・プレビュー・公開できるまでObsidianを維持する
11. 安定運用30日と復元テスト成功後、外部原稿を少なくとも次の月次バックアップ完了まで読み取り専用で保持する。削除は別途承認を得る

現状の3件はテスト記事を含み、front matter形式と必須項目が揃っていないため、移行ツールは「エラー」「警告」「既知の旧形式」を分けて表示する必要がある。

## 11. 既存公開処理との境界

既存スクリプト全体をWeb入力付きでそのまま起動せず、Pythonの安全なサービス関数へ分ける。slugやパスはサーバー側で解決し、任意コマンドを受け取らない。

| 機能 | 管理画面側の責任 | 既存処理から再利用する核 |
|---|---|---|
| 保存 | 原子的保存、競合検出、履歴 | `sync_diary.py` の安全なパス・置換パターン |
| 校正状態確認 | 現在ハッシュとの一致表示 | `review_article.py` のstatus/hash |
| AI校正 | 確認後にジョブ化、本文は変更しない | request/response検査と原子的レポート保存 |
| プレビュー用同期 | 対象記事を一時contentへ変換 | `sync_diary.py` の記事単位変換 |
| 記事検査 | 構造化した警告・エラーを返す | `validate_blog.py` |
| Hugoビルド | 固定引数、固定作業場所、タイムアウト | 現行Hugoコマンド |
| 公開前検査 | ハッシュ、校正、画像、リンク、生成物 | 現行publish前半 |
| stage・commit | 対象記事パスのみ、stage外混入で停止 | 現行publishのGit安全策 |
| push | 最終確認後だけ | 現行publish後半 |
| Pages/URL確認 | commit SHAに対応するrunとHTTP結果を表示 | 現行gh/URL確認 |

長時間処理はジョブIDを払い出し、進行状況と安全なエラーだけをSQLiteへ記録する。標準出力を無制限に画面やDBへ保存せず、秘密らしい値を除去する。公開は「検査」と「実行」を分け、検査時のファイルハッシュと実行時が違えば再承認を要求する。

`publish.ps1` は暫定運用として残す。Phase Eで機能分離が完成するまで削除しない。

## 12. 技術選定

| 候補 | 導入 | 保守/テスト | 画像・SQLite | 非同期/拡張 | 依存/安全性 |
|---|---|---|---|---|---|
| Python標準ライブラリ中心 | 依存最少 | HTTP処理を自作し保守負担大 | 可能だが実装量多い | 弱い | 依存は少ないが自作部分が危険 |
| FastAPI | 少数の依存追加 | 型と入力検査が明確、テストしやすい | 良好 | ジョブAPIへ拡張しやすい | 適切。localhost固定が必要 |
| Flask | 導入容易 | 単純だが規約を別途決める | 良好 | 非同期は追加設計が多い | 少ないが入力モデルは自作寄り |

推奨は FastAPI + Python標準 `sqlite3` + サーバー描画HTML + 通常のCSS/JavaScriptである。Reactは初期版には不要で、ビルド工程、依存、状態管理を増やさない。FastAPIの入力検査と自動テストのしやすさは、保存・公開の誤操作防止に役立つ。

起動時は `127.0.0.1` にだけbindし、外部IPの指定を許可しない。ブラウザからの更新は同一オリジン限定、CSRF対策、Host検査、CORS無効、危険操作の再確認、一度に1プロセスだけのロックを採用する。外部サービス費用はなく、使用するソフトウェアも無償の範囲を想定する。AI校正を実行する場合のAPI利用料は従来どおり別途発生し得る。

## 13. エラー時のデータ保護

- 保存前ハッシュ不一致、SQLite不整合、検査失敗、秘密検出、stage混入、承認不足では停止する
- 途中生成物は `var/admin/` の処理ID別一時領域に置き、成功前に正本へ反映しない
- SQLite更新とファイル置換を単一トランザクションのように扱えないため、操作記録を先に `running` とし、ファイル置換後のハッシュ確認を経て `success` にする
- 起動時に `running` のままの操作を検出し、ファイルと履歴を比較して人へ知らせる。自動的に成功扱いしない
- SQLite破損時はDBを上書きせず別名退避し、正本の読み取り専用スキャンから新DBを作る
- ログには安全なエラーコード、対象記事ID、時刻だけを基本とし、本文、Cookie、token、環境変数値を入れない

## 14. Phase B以降の実装単位とテスト

### Phase B

- 起動/終了、localhost限定、単一起動ロック
- DB初期化・migration・破損検出
- 固定メニュー、履歴・エラー表示、準備中画面
- テスト: 外部bind拒否、Host/CSRF、DB migration、秘密非記録、異常終了復帰

### Phase C

- 原稿スキャン、一覧、新規作成、編集、画像、保存、履歴、競合、アーカイブ
- 移行dry-runと1記事コピー
- テスト: 原子的保存、電源断相当、複数タブ、外部変更、slug/画像パス、SQLite消失再構築、旧形式移行、rollback

### Phase D

- 3記事タイプのテンプレートと必須項目
- テスト: 種類別front matter、未知キー保持、YAML特殊文字、日本語、日付

### Phase E

- 校正、プレビュー、検査、公開確認、記事限定Git操作、Pages/URL確認
- テスト: fake AI、校正ハッシュ不一致、`review-report.md`除外、Hugo失敗、stage混入、承認なしpush禁止、外部通信stub

全Phaseで既存51件、Hugo本番相当ビルド、Git差分、PaperMod submoduleを回帰確認する。実サービスはテストから呼ばない。

## 15. 暫定運用とObsidian終了条件

Phase E完了までは現在の運用を変えない。

1. 外部原稿をObsidianで編集
2. 現在のショートカットまたは `tools/publishing/` で校正・プレビュー
3. 公開は毎回承認して既存処理を使用

Obsidianを外せるのは、全対象記事の移行確認、管理画面での保存・画像・校正・プレビュー・公開、復元テスト、30日間の安定運用が完了した後である。それまではショートカットと外部原稿を残す。

## 16. 承認済みの決定事項

2026-08-09にユーザーが次の5項目をすべて承認した。

1. 正本を `content/articles/` に新設する
2. 技術構成を FastAPI + 通常HTML/CSS/JavaScriptとする
3. 自動保存を「入力後2秒、遅くとも30秒」、履歴を「30世代または90日」とする
4. アーカイブはファイルを動かさない論理方式とする
5. 外部原稿は移行後30日かつ次回月次バックアップ完了まで保持し、その後の削除にも別途承認を必要とする

以上によりPhase Aの設計は確定し、完了条件を満たした。Phase Bの実装開始、依存パッケージ追加、Phase Cでの原稿移行実行は、それぞれの作業依頼・承認範囲に従う。

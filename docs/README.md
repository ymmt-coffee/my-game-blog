# my-game-blog ドキュメント案内

このフォルダには、人が読む仕様、計画、監査記録、操作手順をまとめる。

## 最初に読む資料

1. [`game-blog-operation-plan.html`](game-blog-operation-plan.html) — 運営方針と現在地の概要
2. [`blog_automation_spec.md`](blog_automation_spec.md) — 詳細な運営・自動化仕様
3. [`roadmap.md`](roadmap.md) — 実装順、進捗、完了条件

## 運用時に使う資料

- [`publishing-workflow.md`](publishing-workflow.md) — Obsidianからプレビュー・公開する手順

## 記録資料

- [`phase-0-audit.md`](phase-0-audit.md) — Phase 0実施時点の現状監査結果
- [`phase-1-implementation-report.md`](phase-1-implementation-report.md) — Phase 1の実装内容、テスト結果、保留事項

監査資料は当時の状態を残す記録であり、現在の操作方法と異なる場合がある。現在の公開操作は `publishing-workflow.md`、現在の進捗は `roadmap.md` を優先する。

## 文書以外の関連設定

- `../data/editorial/strategy.yaml` — AIと自動処理が参照する機械可読な運営設定

方針を変更するときは、`blog_automation_spec.md`、`roadmap.md`、`game-blog-operation-plan.html`、`../data/editorial/strategy.yaml` の4資料を同時に更新する。

# my-game-blog ドキュメント案内

このフォルダには、人が読む仕様、計画、監査記録、操作手順をまとめる。

## 最初に読む資料

1. [`../AGENTS.md`](../AGENTS.md) — このリポジトリでAIが必ず守る短い共通指示
2. [`automation-common-rules.md`](automation-common-rules.md) — 全Phase共通の安全、テスト、Git、資料更新ルール
3. [`game-blog-operation-plan.html`](game-blog-operation-plan.html) — 運営方針と現在地の概要
4. [`blog_automation_spec.md`](blog_automation_spec.md) — 詳細な運営・自動化仕様
5. [`roadmap.md`](roadmap.md) — 実装順、進捗、完了条件

## 運用時に使う資料

- [`publishing-workflow.md`](publishing-workflow.md) — Obsidianから校正・プレビュー・公開する手順
- [`backup-and-restore-workflow.md`](backup-and-restore-workflow.md) — Phase 4のバックアップ、容量停止、復元、承認手順

## 記録資料

- [`phase-0-audit.md`](phase-0-audit.md) — Phase 0実施時点の現状監査結果
- [`phase-1-implementation-report.md`](phase-1-implementation-report.md) — Phase 1の実装内容、テスト結果、保留事項
- [`phase-2-implementation-report.md`](phase-2-implementation-report.md) — Phase 2の本文保護、校正レポート、テスト結果、保留事項
- [`phase-3-implementation-report.md`](phase-3-implementation-report.md) — Phase 3のDiscord通知、Pages確認、実Discord疎通、Node.js 24対応の完了記録
- [`phase-4-implementation-report.md`](phase-4-implementation-report.md) — Phase 4の容量実測、暗号化バックアップ、復元、定期実行、通知の完了記録
- [`phase-5-implementation-prompt.md`](phase-5-implementation-prompt.md) — Phase 5「新作・セール5選」を安全に調査・実装するための依頼文

監査資料は当時の状態を残す記録であり、現在の操作方法と異なる場合がある。現在の公開操作は `publishing-workflow.md`、現在の進捗は `roadmap.md` を優先する。

## 文書以外の関連設定

- `../data/editorial/strategy.yaml` — AIと自動処理が参照する機械可読な運営設定

方針を変更するときは、`blog_automation_spec.md`、`roadmap.md`、`game-blog-operation-plan.html`、`publishing-workflow.md`、該当Phaseの実装報告、`../data/editorial/strategy.yaml` を同時に更新する。共通の作業・安全ルールを変更するときは、`../AGENTS.md` と `automation-common-rules.md` も同期する。

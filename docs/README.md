# my-game-blog 現行ドキュメント

2026-08-09から、日常操作をローカル管理画面へ集約する方針へ切り替えた。
最初の目標は、管理画面だけで記事を作成、校正、プレビュー、公開できる状態である。

## 現行資料

1. `automation-common-rules.md` - 安全、外部変更、テストの共通ルール
2. `blog_automation_spec.md` - 新しい管理画面とデータの基本仕様
3. `roadmap.md` - 実装順と完了条件
4. `publishing-workflow.md` - 管理画面完成前の暫定的な記事更新手順
5. `backup-and-restore-workflow.md` - 継続稼働するバックアップ手順
6. `game-blog-operation-plan.html` - ブラウザで確認する新構想の概要
7. `admin-restructure-report.md` - 旧機能の退避と停止内容
8. `folder-structure-report.md` - ブログ本体とツールの分離内容
9. `phase-a-data-migration-design.md` - 承認済みのPhase A設計。記事の正本、状態、SQLite、移行、復元、技術選定
10. `phase-b-admin-shell-report.md` - localhost限定の管理画面土台と安全性の実装報告
11. `phase-c-article-management-report.md` - 記事作成、保存、画像、履歴、競合、アーカイブの実装報告
12. `phase-d-article-templates-report.md` - 3カテゴリーの雛形、種類別入力、必須項目検査の実装報告
13. `phase-e-publishing-report.md` - AI校正、Hugoプレビュー、公開前チェック、記事限定公開の実装報告
14. `phase-f-blog-design-report.md` - 公開ブログのデザイン、明示的なヘッダー画像、モバイル表示の実装報告
15. `site-refactoring-report.md` - Phase A〜F完成後の構成整理、共通化、挙動維持の検証記録
16. `phase-g-scheduling-report.md` - 記事の予約公開、失敗時の安全停止、月・週カレンダーの実装報告
17. `phase-h-analytics-report.md` - 集計済みCSV、期間比較、改善候補、外部サービス保留境界の実装報告

機械可読な現在値は `../config/editorial/strategy.yaml` を参照する。

移行前の外部テスト原稿3件は2026-08-09のユーザー承認によりWindowsのごみ箱へ移動済みで、外部原稿フォルダは空である。管理画面の記事と公開用記事は保持している。

## 保留資料

過去Phase、Discord、週次AI調査などの資料とコードは `../archive/` に退避した。
`archive/` は参考資料であり、現在の操作手順や実装対象ではない。再利用する場合は、現在の安全基準で再設計する。

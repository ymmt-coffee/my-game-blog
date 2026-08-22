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
17. `phase-h-analytics-report.md` - Umami計測、手動エクスポート取込、期間比較、月次レビュー、安全な保留境界の実装報告
18. `phase-i-social-report.md` - X投稿案、確認、コピー、手動投稿記録と、X API連携の保留境界の実装報告
19. `phase-j-shared-game-information-design.md` - Phase J〜Lの承認済み収集条件、採点、外部接続、安全境界、試運転手順
20. `phase-j-shared-game-information-report.md` - Phase JのSQLite共通基盤、バックアップ、Apify接続確認、最大10件候補試運転、保留作業の実装報告
21. `repository-commit-safety-report.md` - 公開リポジトリの個人パス除去と、誤commit防止検査の実装・操作記録
22. `phase-k-ai-editorial-report.md` - 上位3候補、月間予算、購入・プレイ評価、記事形式提案、明示的な下書き作成の実装報告
23. `phase-l-release-sale-report.md` - 情報収集と週刊記事選定の分離、公式再確認、統合下書き、カレンダー連携の実装報告
24. `admin-weekly-dashboard-report.md` - 月〜日の週次進捗、次の作業、記事・選定・プレイ状況をまとめるトップページの実装報告
25. `admin-data-reset-report.md` - テスト運用開始前の記事・管理データ初期化と復元方法の記録
26. `current-state.md` - 次の作業開始時に確認する現在の実装、週間ルーチン、安全境界、保留事項

機械可読な現在値は `../config/editorial/strategy.yaml` を参照する。

2026-08-22に、1から運用テストを始めるため、管理原稿、公開用記事、管理画面の状態・履歴を初期化した。初期化前データは非公開の `var/reset-backups/` に退避しており、公開サイトへの削除反映はcommit・push後に行われる。

## 保留資料

過去Phase、Discord、週次AI調査などの資料とコードは `../archive/` に退避した。
`archive/` は参考資料であり、現在の操作手順や実装対象ではない。再利用する場合は、現在の安全基準で再設計する。

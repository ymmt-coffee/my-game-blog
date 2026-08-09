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

機械可読な現在値は `../data/editorial/strategy.yaml` を参照する。

## 保留資料

過去Phase、Discord、週次AI調査などの資料とコードは `../old/` に退避した。
`old/` は参考資料であり、現在の操作手順や実装対象ではない。再利用する場合は、現在の安全基準で再設計する。

# フォルダ構成整理 実施報告

実施日: 2026-08-09

## 目的

Hugoブログ本体、日常操作ツール、バックアップ、設定、保留機能、自動生成物を役割別に分け、ルートを見ただけで用途を判断できるようにする。

## 新しい構成

- `blog/`: Hugoブログ本体
- `admin/`: ローカル管理画面の実装場所
- `tools/publishing/`: 記事の校正、同期、検査、プレビュー、公開
- `tools/backup/`: 暗号化バックアップ
- `config/editorial/`: 編集方針と校正表示設定
- `config/backup/`: バックアップ設定と除外規則
- `docs/`: 現行資料
- `archive/`: 保留した旧実装と過去資料
- `var/`: ビルド結果、調査成果物、一時ファイル

## 互換性対応

Hugo、GitHub Pages、Python、PowerShell、Obsidian暫定ショートカット、PaperMod submodule、Windowsバックアップタスクの参照先を新しいパスへ変更する。記事本文と公開内容は変更しない。

## 外部設定

- Obsidianのプレビュー、校正、公開ショートカットを `tools/publishing/` へ切り替えた。
- Windowsの日次・月次バックアップタスクの実行先を `tools/backup/run_phase4_backup.ps1` へ切り替えた。
- タスクの実行時刻、有効状態、Wake、再試行、重複実行防止設定は維持した。

## 生成物

`var/` はGit管理対象外であり、ブログ本体ではない。Hugoの公開結果は `var/public/`、画像キャッシュは `var/resources/` に生成する。

## 検証

- 記事関連テスト25件
- バックアップ関連テスト26件
- Python構文検査
- Hugo本番ビルド
- 生成サイト検査
- 記事同期・一時ビルド
- 校正状態確認
- 未承認公開の停止
- バックアップPlan
- PaperMod submodule
- GitHub Actions workflow構文

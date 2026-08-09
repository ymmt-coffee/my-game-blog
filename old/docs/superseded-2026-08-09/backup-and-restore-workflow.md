# Phase 4 バックアップ・復元手順

## 現在の状態

ローカルの安全機能、rclone 1.75.0、Google OAuth、通常remote、crypt remote、rclone設定ファイルのWindowsユーザー保護まで完了している。架空ファイル1件の暗号化アップロード・復元テストと初回バックアップは成功した。日次・月次タスクは登録・有効化済みである。Actions経由のDiscordエラー通知は、実障害と区別した接続テスト1件に成功している。

バックアップ元は `C:\Users\ymmt_\Documents\Life_and_Div` 固定で、処理は元へ書き戻さない。日次は除外後の全体を削除伝播なしでcopyする。月次は`.obsidian`、Obsidian原稿、`my-blog`、`my-game-blog`だけを `YYYY-MM` の固定スナップショットとして12世代保持する。

## 承認前にできる確認

対象件数と容量だけを表示する。ファイル名や本文は表示しない。

```powershell
.\scripts\run_phase4_backup.ps1 -Mode Plan
```

除外規則は `data/backup/exclude-rules.txt`、秘密でない設定は `data/backup/phase4.json` にある。`.gitignore` は使用しない。

## 実バックアップを有効化する前の順序

1. rclone公式安定版のインストール（完了。公式SHA-256確認済み）
2. rclone cryptを使用するか決める（採用決定済み。復旧キー保管先は設定前に確認）
3. 専用GoogleアカウントでOAuthし、remoteを作る
4. 専用テストフォルダを作る
5. 短い架空テキスト1件だけをアップロードする（完了。平文79 bytes）
6. 別のWindows一時領域へ復元し、SHA-256一致を確認する（完了）
7. テストデータを保持するか削除するか決める（ユーザー承認によりDrive上へ保持）
8. フルバックアップのdry-runと容量を確認する
9. タスクスケジューラへ無効状態で登録する（完了）
10. フルバックアップとタスク有効化をそれぞれ承認する（完了）

各承認は後の項目へ自動的に拡張しない。

日次2時と月初3時のタスクは登録・有効化済みである。登録前の設定確認用XMLもリポジトリ外の一時領域へ生成できる。XML生成だけではタスクを変更しない。

```powershell
python scripts\phase4_backup.py task-xml --mode Daily --remote "承認済みremote:承認済み保存先" --output "$env:TEMP\phase4-daily.xml"
python scripts\phase4_backup.py task-xml --mode Monthly --remote "承認済みremote:承認済み保存先" --output "$env:TEMP\phase4-monthly.xml"
```

## 日次・月次と容量

- 日次は `rclone copy` を使用し、元から消えたファイルをDriveから削除しない。
- 月次は `data/backup/monthly-filter-rules.txt` の許可リストだけを対象にし、新しい開発ツールを自動的に12重保存しない。
- 月次は同じ月の検証済み成功マーカーがあれば重複作成しない。
- copy後に `rclone check --one-way` が成功した場合だけ成功マーカーを置く。
- 月次の13個目以降は、新しい月の検証成功後だけ削除候補になる。
- 名前不正、12個以下、作成失敗、検証失敗時は削除候補を作らない。
- 初回のDrive上の削除はdry-run一覧を確認してから別途承認する。
- copy前にDriveの実容量を取得し、予定転送後に1 GiBまたは総容量20%の大きい方を残せなければ停止する。
- 容量情報を取得できない場合も停止する。

## 作業中ファイルと同時実行

同時実行はロックで拒否する。ローカル検証用copyはコピー前後のサイズ・更新時刻とSHA-256を確認し、途中で変化したファイルを完成データへ昇格しない。rclone実行後も全体検証が成功しなければ成功マーカーを作らない。reparse point、junction、symlinkは辿らない。

## 復元

復元先はWindows一時領域または専用の空フォルダにする。現在使用中の `Life_and_Div`、その配下、Obsidian原稿へ直接復元しない。

1. 専用の一時復元フォルダを作る
2. 対象をDriveからcopyする
3. 件数、容量、SHA-256を確認する
4. 内容を人が確認する
5. 現在の原稿へ戻す必要がある場合は、対象と影響を確認して別途実施する

## 認証情報と失敗通知

OAuth token、rclone設定、cryptパスワードはリポジトリ、Obsidian、`.env`、ログ、Discord、GitHub Actions artifactへ保存しない。`rclone.conf`自体も専用パスワードで暗号化済みで、そのパスワードはWindows DPAPIにより現在のWindowsユーザーだけが解除できる状態でユーザー領域へ保存する。設定保護用パスワード、cryptパスワード、salt、復旧手順は、バックアップ対象PCとは別の準備済み復旧情報保管先へ記録する。秘密値は資料へ記録しない。

## タスクスケジューラ

- `my-game-blog Phase4 Daily Backup`: 毎日02:00
- `my-game-blog Phase4 Monthly Snapshot`: 毎月1日03:00
- 現在は2件とも有効で、初回の日次バックアップと月次`2026-08`を検証済みである。
- 予定時刻に停止していた場合は次回起動後に実行し、スリープ中は解除を許可する。
- バッテリー動作中は開始しないが、開始後にバッテリーへ切り替わっても停止しない。
- 重複起動はタスク側とバックアップ側のロックで防ぐ。
- 失敗時は15分間隔で最大2回再試行し、1回の実行上限は2時間とする。
- Windowsへログオン中の現在ユーザー権限で実行し、管理者権限は使用しない。

失敗時はローカルからGitHub Actionsの手動イベントを起動し、Actions側だけが既存の `DISCORD_WEBHOOK_ERROR` を使用する。入力は失敗分類、日時、32桁の実行IDだけで、自由文、個人ファイル名、本文、ログ全文を受け付けない。GitHub CLI認証が利用できない場合は秘密を含まないローカル状態記録だけを残す。通知失敗を理由に成功済みバックアップを削除しない。

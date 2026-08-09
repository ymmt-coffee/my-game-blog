# バックアップと復元

## 現在の状態

暗号化Google Driveバックアップは、管理画面再構築中も記事と設定を守る独立した安全機能として継続する。

- 毎日2時: 除外規則適用後の `Life_and_Div` をcopy
- 毎月1日3時: ブログに必要な範囲の月次スナップショット
- 元から消えたファイルを日次保存先から自動削除しない
- 月次保持候補は検証後にdry-run記録だけを作り、未承認の実削除はしない
- Discord通知は停止済み
- 失敗は `%LOCALAPPDATA%\my-game-blog\phase4-backup` の非公開状態記録へ残す

## 状態確認

```powershell
Get-ScheduledTask -TaskName "my-game-blog Phase4 Daily Backup","my-game-blog Phase4 Monthly Snapshot"
```

計画確認は外部へ書き込まない。

```powershell
.\scripts\run_phase4_backup.ps1 -Mode Plan
```

## 安全策

- rclone設定とOAuth tokenをリポジトリ、ログ、チャットへ表示しない。
- `copy`を使用し、日次では保存先だけにあるファイルを削除しない。
- コピー後に検証し、成功後だけ完了マーカーを作る。
- 元ファイルが処理中に変化した場合は成功扱いにしない。
- Google Driveの安全な空き容量を残せない場合は停止する。
- 復元先に現在の `Life_and_Div` を直接指定しない。

## 復元

まず別の一時フォルダへ復元し、ファイル数、ハッシュ、内容を確認する。現在の原稿への置換は、対象一覧と影響を確認し、ユーザーの明示承認後に行う。

認証情報、暗号化パスワード、復旧情報の値は、この文書やGitへ保存しない。

# 公開リポジトリの誤commit防止 実装報告

## 目的

公開リポジトリへAPIキー、個人ユーザーパス、校正記録、ローカルDB、バックアップ用複製を誤って登録しないため、commit直前にGitへ登録された内容だけを検査する。

## 実装内容

- `tools/security/check_staged_commit.py` がGitのstage内容を読み、公開対象外情報を検出すると終了コード1で停止する。
- `.githooks/pre-commit` により、通常の手動commitでも同じ検査を自動実行する。
- 管理画面の記事公開と公開停止は、対象記事をstageした後、commitの直前に同じ検査を実行する。
- GitHub Actionsは全追跡ファイルを検査し、検出時はHugoビルドと公開へ進まない。
- 検査を起動できない場合もcommitを許可せず、安全側で停止する。

## 停止対象

- 秘密鍵
- GitHub、Google、Apify、Discord、Slackの既知形式のtokenまたはWebhook
- 値が設定されたSteam Web API key
- Windows、macOS、Linuxの個人ホームディレクトリを示す絶対パス
- `review-report.md`
- `.env` とその派生ファイル
- `var/` と `backup-source/`
- PKCS#12形式の秘密鍵ファイル

画像などのバイナリと2MBを超える通常ファイルは内容検査を行わず、禁止パスだけを確認する。記事本文や画像の通常commitは妨げない。

## ローカル設定

このリポジトリでは次を一度実行し、Git hookの保存場所を `.githooks` に固定する。

```powershell
.\tools\security\install-commit-guard.ps1
```

別PCへcloneした場合も同じ操作が必要である。GitHub Actions側の検査はclone先の設定に依存せず常に実行される。

## 安全境界

この検査は誤登録の可能性を下げる補助策であり、秘密情報をGitへstageしない運用とGitHubのSecret scanning・Push protectionを置き換えない。誤検知時は検査を無効化せず、対象ファイルまたは記載方法を確認する。

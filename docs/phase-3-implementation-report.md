# Phase 3「GitHub PagesとDiscord通知」実装結果

- 実施日: 2026-08-02（Asia/Tokyo）
- 対象: `my-game-blog`
- 状態: Phase 3実装・fakeテスト・GitHub Secrets・実Discord3件・commit・push・Actions・Pages・Node.js 24確認完了
- 外部変更: 3つのGitHub Secretsをユーザーが登録し、名前だけを確認。接続テストを3チャンネルへ各1件・合計3件送信。Phase 3をcommit・pushし、ActionsとPagesを確認。Webhook値は取得・表示していない

## 1. 変更前の基準

- Git: `main`、`origin/main` と一致、作業ツリーはクリーン、stage済み変更なし
- remote: `origin` は `ymmt-coffee/my-game-blog`
- PaperMod submodule: commit `154d006e0182dfc7da38008323976b02e6bfab4a`、変更なし
- Python: 3.14.4
- Hugo: 0.163.2 extended
- 既存自動テスト: Phase 1・2の合計25件すべて成功
- Hugo本番相当ビルド: 成功。既存テーマ由来のHugo非推奨警告1件のみ
- 変更前Actions: push、毎朝8時のschedule、手動実行のすべてが同じbuild・deployを行う。成功通知と失敗通知は未実装
- 変更前公開確認: `publish.ps1` がpush後にActions完了とPagesトップURLのHTTP 200を確認する

## 2. 実装前に決めたこと

### GitHub Secrets名

| Secret名 | Discordチャンネル |
|---|---|
| `DISCORD_WEBHOOK_PUBLISH` | `公開通知` |
| `DISCORD_WEBHOOK_ERROR` | `エラー通知` |
| `DISCORD_WEBHOOK_ATTENTION` | `要確認` |

Webhook URLは環境変数からだけ読み、値をチャット、コマンド、ログ、リポジトリへ表示・保存しない。

### トリガーと通知条件

- push: push後のHEAD commit件名が厳密に `publish: <安全なslug>` で、push全体の変更がその記事フォルダ内だけの場合に限り、全確認後に `公開通知`
- 通常のコード・資料push: 成功通知なし
- schedule: 成功通知なし。技術的失敗だけ `エラー通知`
- workflow_dispatch: 成功通知なし。技術的失敗だけ `エラー通知`
- `publish:` で始まるがslugが不正、空、または変更範囲と一致しない: deployとPages確認が成功した後に `要確認`
- 校正レポートなし・古いレポート: GitHubへ安全に渡す方式を今回は決めず、通知判定へ含めない

### 通知失敗

通知失敗はActions全体で見える失敗にする。ただし、公開済み記事、Git commit、GitHub Pagesを削除、revert、再commitしない。`公開通知` または `要確認` が失敗した場合は、可能なら `エラー通知` へ通知する。`エラー通知` 自体の失敗は再帰的に別通知しない。

### 再試行と重複

- 429と5xxだけ、初回を含め最大3回
- 429の `Retry-After` は最大10秒に制限
- 5xxは1秒、2秒相当の短い待機
- 400、401、403等の4xxは再試行しない
- 通信切断・タイムアウトは、実際にはDiscordが受信済みか判断できないため再試行しない
- 同一スクリプト実行で成功後に再送しない
- workflow全体の手動再実行ではDiscord側に冪等キー機能がないため重複し得る。commitの短い識別子とActions実行URLで同じ事象を判別できるようにする

### 実Discordテスト計画

本番公開を故意に失敗させず、手動実行の `discord_test` を明示的に有効にした場合だけ、`--test-message` で「実際の公開・失敗・要確認は発生していない」と明記した文を `公開通知`、`エラー通知`、`要確認` へ各1件、合計3件だけ送る。2026-08-02にこの方法で3件を送り、すべて成功した。

## 3. 実装内容

### 単体テスト可能な通知スクリプト

`scripts/discord_notify.py` を追加し、次を分離した。

1. push、schedule、手動実行の分類
2. `publish: <slug>` と変更範囲の安全な対応確認
3. Pagesトップと対象記事URLのHTTP 200確認
4. 公開、エラー、要確認の最小JSON生成
5. Discord Webhook送信と限定再試行
6. build、deploy、公開URL確認、通知失敗の段階判定

記事slug、commitメッセージ、URLをコマンドとして実行しない。Git情報を読む場合も引数配列で固定したコマンドだけを呼び、通知送信処理にはGitや記事ファイルを書き換える機能を持たせていない。

### 通知内容と秘密情報保護

許可する情報は次だけである。

- 通知種別
- 記事slugまたは失敗段階
- 公開URL
- commit SHAの先頭12文字
- push、schedule、手動実行の種別
- Actions実行URL

記事本文、校正レポート本文、Webhook URL、APIキー、ログ全文、HTTP応答本文は送らない。Discord JSONの `allowed_mentions` で全メンションを無効にした。Webhook URLは該当Secretから環境変数へ渡すときだけ読み、未設定時はSecret名だけを表示して停止する。

Webhookの接続先はHTTPSのDiscord公式ホストとWebhook用pathだけを許可し、HTTP redirectを追跡しない。これによりWebhook情報を別ホストへ転送しない。

### GitHub Actionsの処理順

`.github/workflows/hugo.yml` を次のjobへ分けた。

1. `build`: トリガーとcommitを分類し、Hugo buildとartifact作成
2. `deploy`: build成功時だけGitHub Pagesへ配置
3. `verify`: deploy成功時だけPagesトップを確認し、公開通知候補なら対象記事URLも確認
4. `notify_publish`: 全確認成功かつ安全な記事公開pushだけ実行
5. `notify_attention`: 全確認成功だが公開対象を安全に特定できないpushだけ実行
6. `notify_error`: build、deploy、URL確認、前段の通知が失敗・キャンセルされた場合に実行

build失敗時はdeploy、URL確認、成功通知を開始しない。deploy失敗時はURL確認と成功通知を開始しない。URL確認失敗時も成功通知を開始しない。失敗通知jobは `always()` と各job結果を使うため、build失敗時にも起動対象になる。

### Node.js 20廃止対応

GitHub公式告知ではNode.js 20は2026年4月にEOLとなり、GitHub-hosted runnerは2026年6月16日からNode.js 24を既定とし、2026年秋にNode.js 20を削除する予定である。

- `actions/checkout` をNode.js 24対応のv6へ更新
- `peaceiris/actions-hugo` をNode.js 24対応のv3.2.0へ更新
- `actions/upload-pages-artifact` をNode.js 24版のartifact処理を使う公式v5へ更新
- `actions/deploy-pages` を `node24` で動く公式v5へ更新
- Node.js 20へ戻す一時回避設定は使用しない

最初のpushではPages artifact v3内部の `actions/upload-artifact@v4` がNode.js 20対象のため、Node.js 24へ強制実行している警告が1件残った。GitHub公式リリースを再確認し、2026-04-10公開のPages artifact v5と2026-03-25公開のdeploy v5が利用可能であることを確認したため、両方をv5へ追補更新した。追補後のGitHub-hosted runnerで警告が消え、build・deploy・verifyに成功した。

## 4. 警告と停止条件

### `要確認` へ送る条件

- push後のHEAD commitが `publish:` で始まるがslugがない
- slugに絶対path、`..`、大文字、空白、許可外文字等がある
- `publish: <slug>` と実際の変更記事フォルダが一致しない
- 公開commitへ対象記事外の変更が混在する

これらはbuild、deploy、Pages確認に成功した場合だけ `要確認` へ送る。技術的に失敗した場合は `エラー通知` を優先する。

### 技術的失敗として扱う条件

- 分類またはHugo build失敗
- artifact作成失敗
- Pages deploy失敗
- Pagesトップまたは対象記事URL確認失敗
- Webhook未設定または形式不正
- Discord通知失敗

通知の失敗は公開の取り消し条件ではない。SNS等の後続Phaseは未実装であり、Phase 3失敗から開始される後続処理もない。

## 5. テスト結果

最終確認結果は次のとおり。

- 既存Phase 1・2テスト: 25件すべて成功
- Phase 3 fake・stubテスト: 15件すべて成功
- 全自動テスト: 合計40件すべて成功
- Python構文検査: 成功
- GitHub Actions YAML解析・構造確認: 成功
- YAML・JSON解析: 成功
- Hugo 0.163.2 extended本番相当ビルド: 成功
- Git差分・秘密情報らしい値・`review-report.md` 混入確認: 成功
- 実Discord API呼出: 接続テスト3件、すべて成功

Phase 3テストは次を直接確認した。

- 公開成功とbuild、deploy、URL確認失敗の通知内容を区別
- 不正slug、空slug、対象外変更、変更記事不一致を `要確認` に分類
- 通常commitでは公開通知なし
- push、schedule、workflow_dispatchを区別
- Secret未設定時はSecret名だけを表示し、値を表示しない
- 通知JSONでメンションを無効化し、Webhookや秘密情報を含めない
- 429・5xxだけ最大3回、400・401・403は1回で停止
- 結果不明の通信失敗を再試行しない
- 通知失敗時に記事ファイルとGit処理を変更しない
- build失敗時に成功通知jobへ進まないworkflow依存関係
- テストコードに実Discord endpointを置かず、すべてfake transportを使用

本番公開を故意に失敗させるテストは行っていない。

## 6. 資料同期

現在状態と操作方法を次へ同期した。

- `docs/blog_automation_spec.md`
- `docs/roadmap.md`
- `data/editorial/strategy.yaml`
- `docs/game-blog-operation-plan.html`
- `docs/publishing-workflow.md`
- `docs/README.md`
- 本書 `docs/phase-3-implementation-report.md`

共通安全ルール自体は変更していないため、`AGENTS.md` と `docs/automation-common-rules.md` は変更していない。Phase 2実装報告は当時の記録として変更していない。

## 7. 外部変更と実施状況

2026-08-02 14:03頃、次の3つのGitHub Secrets名が登録済みであることを `gh secret list` で確認した。GitHub Secretsは値を読み返せないため、Webhook URLは取得・表示していない。

- `DISCORD_WEBHOOK_PUBLISH`
- `DISCORD_WEBHOOK_ERROR`
- `DISCORD_WEBHOOK_ATTENTION`

実施結果:

- Phase 3 commit: `48a315b6837f18c652ecb59f151dbc91f2256544`
- `main` へpush: 成功
- push Actions run `30733563196`: build、deploy、verify成功。通常pushのため通知jobはすべてスキップ
- 接続テスト Actions run `30733597631`: build、deploy、verify、3チャンネル通知がすべて成功
- Node.js 24追補commit `a20911ff4f196167974e5f7a85639fecab4d138d`、Actions run `30733775265`: build、deploy、verify成功、Node.js 20警告なし
- 完了資料commit `23aad9c7183e24f42fd60171c36a418c4f802a08`、Actions run `30733872951`: build、deploy、verify成功
- 実Discord投稿: `公開通知`、`エラー通知`、`要確認` へ各1件、合計3件
- 通常の公開・エラー・要確認通知: 0件
- GitHub Pages: Actions内のPagesトップURL確認に成功
- 秘密情報: Secret名だけを確認し、値は取得・表示していない

最初のActionsでNode.js 20対象Actionの強制実行警告が1件残ったため、Pages公式v5へ追補更新した。追補commit `a20911ff4f196167974e5f7a85639fecab4d138d` のActions run `30733775265` でbuild、deploy、verifyがすべて成功し、Node.js 20警告が表示されないことを確認した。Pagesトップと既存記事 `publishing-test` は直接確認でもHTTP 200を返した。

## 8. 判定

Phase 3のローカル実装とfakeテストは完了した。秘密情報をリポジトリへ置かず、記事公開成功、技術的失敗、人の判断が必要な状態を分離できる。通知失敗が公開済み記事やGit履歴を巻き戻さないことも設計・テストした。

実Discord 3チャンネル、GitHub Secrets、GitHub-hosted Actions、実Pages反映、Node.js 24公式Pages v5まで確認した。通知は承認した接続テスト3件だけで、秘密情報の表示、記事やGit履歴の巻き戻し、意図しない成功通知は発生していない。Phase 3は完了し、Phase 4へ進める状態である。

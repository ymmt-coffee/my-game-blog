# Gemini週次リサーチの設定と使い方

## 現在できること

`scripts/weekly_research.py`はGeminiのGoogle検索とURL参照を使い、作品候補と公式情報を収集します。その後、App ID、記事区分、割引率、JP/JPY、確認日時をプログラム側で整えてから既存のPhase 5検証へ渡します。通過した候補から、ローカルHTML、Discordで読みやすいPDF、メンション無効のDiscord要約JSON、選択用JSON、再利用可能な検証済み結果JSONを作ります。

実Geminiで新作5件・セール5件を取得し、DiscordへのPDF投稿まで確認済みです。毎週日曜18時（日本時間）の定期調査も有効です。Google Drive保存と記事公開は行っていません。HTMLとPDFは確認資料であり、公開前にはSteam等の公式ページを人が再確認します。

## Gemini API側の準備

1. Google AI Studioで、Phase 2と同じGoogle Cloudプロジェクトを選びます。
2. そのプロジェクトで新しいAuth keyを作成します。2026年9月に従来の無制限Standard keyが利用できなくなる予定のため、既存のPhase 2用キーがStandard keyならこの機会にAuth keyへ切り替えます。既存キーがAuth keyなら同じ`GEMINI_API_KEY`を使えます。
3. Google検索を継続利用する場合は、同じプロジェクトへCloud Billingを関連付けます。
4. Google Cloudの「お支払い → 予算とアラート」で、月500円を早期警告、月1,000円を停止判断の目安として通知設定します。予算アラート自体は利用を自動停止しません。
5. Windowsの「環境変数を編集」で、ユーザー環境変数`GEMINI_API_KEY`へキーを設定します。値をリポジトリ、`.env`、Obsidian、Discord、コマンド履歴へ書きません。
6. CodexとPowerShellを閉じ、新しく開き直します。

スクリプト側ではモデルを`gemini-3.6-flash`へ固定し、単発の`generate_content`として呼び出します。候補は最大12件、申告された検索回数は最大20回まで受け付けます。ただしAPI利用額をリアルタイムで正確に取得して強制停止する仕組みではないため、Google Cloud側の予算通知も併用します。

## まず架空データで確認

```powershell
python scripts\weekly_research.py --week 2026-W33 --response-file data\editorial\weekly-research-fake-response.json --output output\weekly-research-fake
```

作られるものは次の5つです。

- `weekly-research.html`: PCで保管・確認する詳細版
- `weekly-research.pdf`: Discordへ添付する閲覧版
- `discord-summary.json`: Discordへ送る最小要約の確認用。まだ自動送信しません
- `selection.json`: 人が選んだ5本のApp IDを記入するファイル
- `research-result.json`: 選択後の下書き生成に使う検証済み候補データ

## 実Geminiを1回だけ試す場合

実行前にユーザー承認を取り、対象週を正しいISO週へ置き換えます。

```powershell
python scripts\weekly_research.py --week YYYY-Www --gemini --output output\weekly-research-live
```

候補が5件未満、公式一次情報なし、価格矛盾、対象週外、危険な文字列、過去掲載との重複の場合は停止します。Geminiの回答全文やAPIキーはログへ出しません。

## DiscordとGoogle Drive

推奨運用は、HTMLをローカルの正本として保管し、専用の「週次リサーチ」チャンネルへ3行の要約とPDFを投稿する形です。Google Driveへ置く場合もHTMLの直接表示には向かないため、保管・バックアップ先として扱います。

Discordは専用の`週次リサーチ`チャンネルを使い、Secret名は`DISCORD_WEBHOOK_WEEKLY_RESEARCH`です。Webhook URLはGitHub Actions Secretだけに保存し、要約ではメンションを無効化します。GitHub Actionsは毎週日曜18時に実行し、確認資料を14日間保存します。Driveアップロードは行いません。

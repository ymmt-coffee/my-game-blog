# 新作・セール5選の候補入力と下書き作成

## 現在の運用範囲

Geminiで候補と出典を収集し、プログラム側で価格・日時・区分を整形・検証します。新作5本とセール5本から人が合計5本を選ぶ実運用まで確認済みです。生成先は指定した新規フォルダだけで、既存原稿を上書きしません。Gemini側の準備と確認方法は[`gemini-weekly-research-setup.md`](gemini-weekly-research-setup.md)を参照してください。

Geminiリサーチでは、新作候補5本とセール候補5本を目標に並べ、HTMLまたはPDFを見て人が掲載する5本を選びます。`selection.json`の`selected_app_ids`へ選んだ5本のApp IDを入れる方式で、AIによる最終5本の自動決定は行いません。候補不足の場合は実際に確認できた本数を表示します。

選択後は次の1コマンドで、保存した検証済み結果と選択内容を接続します。

```powershell
python scripts/apply_weekly_selection.py --research-result output/weekly-research-live/research-result.json --selection output/weekly-research-live/selection.json --history data/editorial/weekly-picks-history.json --output output/weekly-picks-draft
```

Discord通知は`weekly_research_notify.py`が要約JSONとPDFを専用Webhookへ送ります。Webhook URLは`DISCORD_WEBHOOK_WEEKLY_RESEARCH`だけから読み、リポジトリやログへ保存しません。

## 日曜までに候補を集める

1. Steamの「近日中リリース」で対象週の新作を確認する
2. Steamのウィッシュリストとスペシャルで20%以上のセールを確認する
3. 必要ならSteamDB等を候補発見や価格履歴の補助に使う
4. 最終的な発売日、JP/JPY価格、割引、日本語対応はSteam、開発元、販売元の公式ページで確認する
5. 合計8〜12本程度を入力候補にする

デモ、DLC、サウンドトラック、バンドル、地域不明、日本円不明、通常価格不明、日付が曖昧な新作は初期対象外です。早期アクセスは `early_access` と明記します。

## 入力ファイル

`data/editorial/weekly-picks-input-template.json` を作業用の別名へコピーし、プレースホルダーを実際に公式確認した値へ置き換えて使います。テンプレートの値のままでは検査に通りません。候補は最低5本必要で、新作とセールを最低1本ずつ含めます。

日本語対応は次を混同せず入力します。

- `interface`: インターフェイス
- `subtitles`: 字幕
- `full_audio`: フル音声
- `null`: 公式情報で確認できず不明

`editorial_rank` は0〜100で、大きいほど優先します。同点では作品名、App IDの順で決まるため、同じ入力から同じ5本が選ばれます。`personal_comment` は空でも構いません。

## 書き込まずに検査する

```powershell
python scripts/weekly_picks.py --input C:\path\to\weekly-input.json --history data\editorial\weekly-picks-history.json --dry-run
```

AIへ送信可能な情報だけを確認する場合は、`--print-ai-request` を追加します。これは画面表示だけで、AI通信はしません。私感、ページ全文、Cookie、token、別記事、個人メモは含まれません。

## 新規フォルダへ下書きを生成する

```powershell
python scripts/weekly_picks.py --input C:\path\to\weekly-input.json --history data\editorial\weekly-picks-history.json --output C:\path\to\new-draft-folder
```

生成物は次のとおりです。

- `index.md`: `draft: true`の未プレイ記事下書き
- `weekly-picks-evidence.json`: 選定作品、出典、確認日時、外部送信件数0の非公開証跡
- `ai-request-dry-run.json`: AI許可リストの確認用。実送信なし
- `social/0730.txt`, `social/2000.txt`: URL未確定のローカルSNS素材

同じ出力先が存在する場合は停止し、自動上書きしません。正式なObsidian保存先へ置く操作は、内容と送信範囲を確認した後の別承認で行います。

## 停止する主な条件

- 合格候補が5本未満
- 新作またはセールが0本
- 新作の発売日が対象週外
- セールが20%未満、または価格からの再計算と不一致
- JP/JPY、通常価格、公式一次情報が不明
- 公式情報の矛盾、発売延期、価格変動
- 週ID、App ID、Steam URL、過去掲載作品の重複
- AI応答が公式事実のハッシュと一致しない

## 公開との境界

下書き生成は公開承認ではありません。公開する場合は内容を確認し、従来どおりObsidianで `draft: false` に変更してから、記事単位の公開操作を明示承認します。通常push、schedule、手動Actionsを公開承認として扱いません。

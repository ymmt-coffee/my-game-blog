# FRAMING X用ブランド画像

- `framing-x-icon.png`: Xのプロフィール画像用、800×800px。円形切り抜きでも主要部分が欠けない。
- `framing-x-header.png`: Xのヘッダー用、1500×500px。スマートフォンの左右切れと左下のアイコン重なりを避けた中央配置。
- 同名のSVGは編集用の元データ。

黒、濃淡グレー、白だけを使用し、公開ブログの直線的なデザインと合わせている。PNGをXへアップロードし、表示位置を確認してから保存する。

PNGを作り直す場合は、プロジェクト直下で次を実行する。

```powershell
python tools/render_social_brand.py
```

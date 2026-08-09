"""記事カテゴリー別の雛形と、公開前にも再利用できる必須項目検査。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ArticleTemplate:
    key: str
    label: str
    guidance: str
    body: str
    required_metadata: tuple[str, ...]


COMMON_REQUIRED = ("title", "date", "lastmod", "draft", "description", "images", "article_type", "author")

TEMPLATES = {
    "play_note": ArticleTemplate(
        "play_note",
        "プレイ途中記",
        "遊んだ範囲を明記し、未到達部分の断定や大きなネタバレを避けます。",
        """## 今回遊んだところ

ここに進行状況を書きます。

## 印象に残ったこと

面白かった点や気になった点を書きます。

## 次に遊びたいこと

次回の目標を書きます。""",
        COMMON_REQUIRED + ("play_time",),
    ),
    "weekly_picks": ArticleTemplate(
        "weekly_picks",
        "新作・セール5選",
        "5本それぞれについて、確認日時・情報源・価格などの事実確認が必要です。未プレイ作品は未プレイと明記します。",
        """## 今週の選定方針

今回の5本を選んだ基準を書きます。

## 1. ゲームタイトル

- 注目ポイント：
- 発売日・セール期間：
- 価格：
- 日本語対応：
- 情報源：

## 2. ゲームタイトル

## 3. ゲームタイトル

## 4. ゲームタイトル

## 5. ゲームタイトル

## まとめ

5本を振り返ります。""",
        COMMON_REQUIRED,
    ),
    "monthly_essay": ArticleTemplate(
        "monthly_essay",
        "月次レビューエッセイ",
        "その月の体験を一つのテーマで振り返り、作品の紹介だけでなく自分の考えをまとめます。",
        """## 今月のテーマ

今月を振り返るテーマを書きます。

## 心に残ったゲームと体験

具体的な出来事を書きます。

## そこから考えたこと

体験から得た気づきを掘り下げます。

## 来月に向けて

次の月に遊びたいことを書きます。""",
        COMMON_REQUIRED,
    ),
}


def get_template(article_type: str) -> ArticleTemplate:
    try:
        return TEMPLATES[article_type]
    except KeyError as exc:
        raise ValueError("カテゴリーが正しくありません。") from exc


def initial_metadata(title: str, article_type: str, author: str, description: str, play_time: str = "") -> dict[str, object]:
    template = get_template(article_type)
    today = date.today().isoformat()
    metadata: dict[str, object] = {
        "title": title.strip(), "date": today, "lastmod": today, "draft": True,
        "description": description.strip(), "images": [], "article_type": article_type, "author": author.strip(),
    }
    if template.key == "play_note":
        metadata["play_time"] = play_time.strip()
    return metadata


def validate_metadata(metadata: dict[str, object]) -> list[str]:
    article_type = str(metadata.get("article_type") or "")
    if article_type not in TEMPLATES:
        return ["カテゴリーが正しくありません。"]
    messages: list[str] = []
    labels = {
        "title": "タイトル", "date": "公開日", "lastmod": "更新日", "draft": "下書き設定",
        "description": "概要", "images": "画像一覧", "article_type": "カテゴリー", "author": "著者", "play_time": "プレイ時間",
    }
    for key in TEMPLATES[article_type].required_metadata:
        if key not in metadata or metadata[key] is None or (isinstance(metadata[key], str) and not metadata[key].strip()):
            messages.append(f"{labels[key]}が未入力です。")
    for key in ("date", "lastmod"):
        value = metadata.get(key)
        if value not in (None, ""):
            try:
                date.fromisoformat(str(value))
            except ValueError:
                messages.append(f"{labels[key]}はYYYY-MM-DD形式で入力してください。")
    if "images" in metadata and not isinstance(metadata["images"], list):
        messages.append("画像一覧の形式が正しくありません。")
    if "draft" in metadata and not isinstance(metadata["draft"], bool):
        messages.append("下書き設定の形式が正しくありません。")
    if metadata.get("article_type") != article_type:
        messages.append("カテゴリー情報が一致しません。")
    return messages

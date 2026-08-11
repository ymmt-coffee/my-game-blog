"""管理画面から受け取る記事入力値を一つの形式へ揃える。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _boolean(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return _text(value).strip().casefold() == "true"


@dataclass(frozen=True)
class ArticleInput:
    """新規作成、手動保存、自動保存で共有する記事入力。"""

    title: str
    description: str
    article_type: str
    body: str
    play_time: str
    game_completed: bool
    author: str

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> "ArticleInput":
        return cls(
            title=_text(values.get("title")),
            description=_text(values.get("description")),
            article_type=_text(values.get("article_type")),
            body=_text(values.get("body")),
            play_time=_text(values.get("play_time")),
            game_completed=_boolean(values.get("game_completed")),
            author=_text(values.get("author")),
        )

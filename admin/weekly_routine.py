"""トップページの週間ルーチンと週次収集状態を扱う副作用のない処理。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone


WEEKLY_TASKS = (
    ("月", (("レビュー：プレイ・執筆", "/articles"),)),
    ("火", (("レビュー：プレイ・執筆", "/articles"),)),
    ("水", (("レビュー記事を予約公開", "/schedule"),)),
    ("木", (("新作・セール：情報収集", "/collection"),)),
    ("金", (
        ("新作・セール：選定・執筆", "/releases"),
        ("レビュー：プレイ・執筆", "/articles"),
    )),
    ("土", (
        ("新作・セール：仕上げ", "/articles"),
        ("レビュー：プレイ・執筆", "/articles"),
    )),
    ("日", (
        ("新作・セールを公開", "/articles"),
        ("レビュー原稿を仕上げる", "/articles"),
        ("次にプレイするゲームを決定", "/editorial"),
    )),
)


@dataclass(frozen=True)
class CollectionAction:
    state: str
    label: str
    enabled: bool


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def retry_at(run: dict[str, object] | None) -> datetime | None:
    if not run or str(run.get("status")) != "failure":
        return None
    value = run.get("completed_at") or run.get("started_at")
    try:
        return datetime.fromisoformat(str(value)) + timedelta(hours=6)
    except (TypeError, ValueError):
        return None


def collection_action(
    run: dict[str, object] | None,
    *,
    ready: bool,
    now: datetime,
    due_at: datetime | None = None,
) -> CollectionAction:
    if run and str(run.get("status")) in {"success", "partial", "running"}:
        return CollectionAction("done", "更新済み", False)
    retry = retry_at(run)
    if retry and now.astimezone(timezone.utc) < retry:
        return CollectionAction("cooldown", f"{retry.astimezone(now.tzinfo).strftime('%H:%M')}以降再試行", False)
    if due_at and now < due_at:
        return CollectionAction("not_due", "木曜8時から", False)
    if ready:
        return CollectionAction("ready", "情報収集", True)
    return CollectionAction("not_ready", "API設定を確認してください", False)

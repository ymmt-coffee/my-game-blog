"""Phase Gの予約日時変換と安全な期限到来処理。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from admin import articles, db, publishing

JST = ZoneInfo("Asia/Tokyo")


def parse_local_datetime(value: str, *, now: datetime | None = None) -> datetime:
    try:
        local = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("予約日時を正しく入力してください。") from exc
    if local.tzinfo is None:
        local = local.replace(tzinfo=JST)
    instant = local.astimezone(timezone.utc)
    current = now or datetime.now(timezone.utc)
    if instant <= current:
        raise ValueError("予約日時は現在より後にしてください。")
    return instant


def local_value(value: object) -> str:
    if not value:
        return ""
    return datetime.fromisoformat(str(value)).astimezone(JST).strftime("%Y-%m-%dT%H:%M")


def display_datetime(value: object) -> str:
    if not value:
        return ""
    local = datetime.fromisoformat(str(value)).astimezone(JST)
    return f"{local.year}年{local.month}月{local.day}日 {local:%H:%M}"


def process_due_schedules(
    db_path: Path,
    state_root: Path,
    runner: publishing.CommandRunner,
    *,
    now: datetime | None = None,
) -> list[tuple[str, str]]:
    instant = now or datetime.now(timezone.utc)
    results: list[tuple[str, str]] = []
    for record in db.claim_due_schedules(instant.isoformat(timespec="seconds"), db_path):
        article_id = str(record["id"])
        try:
            article = articles.read_article(Path(str(record["source_path"])), article_id, str(record["slug"]))
            if str(record.get("file_hash")) != article.file_hash or str(record.get("scheduled_file_hash")) != article.file_hash:
                raise publishing.PublishError("予約後に原稿が変更されたため、自動公開を停止しました。")
            prepared = state_root / "publish-prepared" / article_id / article.file_hash
            sha, pages_url = publishing.publish_article(article, prepared, runner)
            db.mark_published(article_id, article.file_hash, db_path)
            results.append((article_id, "published"))
        except Exception as exc:
            message = str(exc) if isinstance(exc, (articles.ArticleError, publishing.PublishError, RuntimeError)) else "予約公開で予期しないエラーが発生しました。管理原稿は保持されています。"
            db.fail_schedule(article_id, message, db_path)
            results.append((article_id, "failed"))
    return results

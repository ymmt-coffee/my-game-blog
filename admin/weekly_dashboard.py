"""管理画面トップに表示する週次進捗の読み取り専用集計。"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from admin import articles, db, scheduling


ACTIVE_EDIT_STATES = {"draft", "review_pending", "ready", "scheduled"}


def _as_jst(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(scheduling.JST)


def _week_bounds(now: datetime) -> tuple[datetime, datetime]:
    local = now.astimezone(scheduling.JST)
    monday = local.date() - timedelta(days=local.weekday())
    start = datetime.combine(monday, time.min, scheduling.JST)
    return start, start + timedelta(days=7)


def _in_range(value: object, start: datetime, end: datetime) -> bool:
    parsed = _as_jst(value)
    return parsed is not None and start <= parsed < end


def _article_title(record: dict[str, object]) -> str:
    try:
        article = articles.read_article(
            Path(str(record["source_path"])), str(record["id"]), str(record["slug"]),
        )
        return str(article.metadata.get("title") or record["slug"])
    except (articles.ArticleError, OSError, KeyError):
        return str(record.get("slug") or "記事")


def _article_action(record: dict[str, object]) -> str:
    state = str(record.get("state") or "")
    if state == "ready":
        return "最終確認"
    if state == "scheduled":
        return "予約確認"
    if state == "published":
        return "公開済み"
    return "編集を続ける"


def _latest_cycle(connection) -> str:
    row = connection.execute("SELECT MAX(cycle_key) FROM game_candidates").fetchone()
    return str(row[0] or "") if row else ""


def build(db_path: Path, now: datetime | None = None) -> dict[str, object]:
    """既存データを変更せず、今週と前週の進捗をまとめる。"""
    current = (now or datetime.now(scheduling.JST)).astimezone(scheduling.JST)
    week_start, week_end = _week_bounds(current)
    previous_start = week_start - timedelta(days=7)
    records = db.list_articles(db_path)

    def active_this_week(record: dict[str, object]) -> bool:
        dates = (record.get("created_at"), record.get("updated_at"), record.get("scheduled_at"), record.get("published_at"))
        return any(_in_range(value, week_start, week_end) for value in dates) or str(record.get("state")) in ACTIVE_EDIT_STATES

    def touched_in(record: dict[str, object], start: datetime, end: datetime) -> bool:
        return any(_in_range(record.get(key), start, end) for key in ("created_at", "updated_at"))

    published = [row for row in records if _in_range(row.get("published_at"), week_start, week_end)]
    previous_published = [row for row in records if _in_range(row.get("published_at"), previous_start, week_start)]
    produced = [row for row in records if touched_in(row, week_start, week_end)]
    previous_produced = [row for row in records if touched_in(row, previous_start, week_start)]
    weekly_articles = sorted(
        (row for row in records if active_this_week(row)),
        key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True,
    )[:5]
    for row in weekly_articles:
        row["display_title"] = _article_title(row)
        row["action_label"] = _article_action(row)

    warnings: list[dict[str, str]] = []
    overdue: list[dict[str, object]] = []
    today = current.date()
    due_today: list[dict[str, object]] = []
    for row in records:
        if row.get("schedule_error"):
            warnings.append({"text": f"{_article_title(row)}の予約公開が停止しています。", "url": f'/articles/{row["id"]}/edit'})
        scheduled = _as_jst(row.get("scheduled_at"))
        if str(row.get("state")) == "scheduled" and scheduled:
            if scheduled < current:
                overdue.append(row)
                warnings.append({"text": f"{_article_title(row)}の予約時刻を過ぎています。", "url": f'/articles/{row["id"]}/edit'})
            elif scheduled.date() == today:
                due_today.append(row)

    with closing(db.connect(db_path)) as connection:
        cycle = _latest_cycle(connection)
        candidate_counts = {"new_release": 0, "sale": 0}
        selection_counts = {"new_release": 0, "sale": 0}
        if cycle:
            candidate_counts["new_release"] = int(connection.execute(
                "SELECT COUNT(*) FROM game_candidates WHERE cycle_key=? AND status='active' AND candidate_kind='new_release'", (cycle,),
            ).fetchone()[0])
            candidate_counts["sale"] = int(connection.execute(
                "SELECT COUNT(*) FROM game_candidates WHERE cycle_key=? AND status='active' AND candidate_kind IN ('sale','free')", (cycle,),
            ).fetchone()[0])
            for row in connection.execute(
                "SELECT selection_kind,COUNT(*) FROM weekly_release_selections WHERE cycle_key=? GROUP BY selection_kind", (cycle,),
            ).fetchall():
                selection_counts[str(row[0])] = int(row[1])

        latest_run = connection.execute(
            "SELECT * FROM game_collection_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        current_run = dict(latest_run) if latest_run and _in_range(latest_run["started_at"], week_start, week_end) else None
        if current_run and str(current_run["status"]) in {"partial", "failure"}:
            warnings.append({"text": "今週の情報収集に確認事項があります。", "url": "/collection"})

        social_pending = int(connection.execute(
            "SELECT COUNT(*) FROM social_drafts WHERE status IN ('draft','reviewed')"
        ).fetchone()[0])
        play_candidates = int(connection.execute(
            """SELECT COUNT(*) FROM game_decisions d
               WHERE d.decision='play_candidate' AND NOT EXISTS
               (SELECT 1 FROM game_decisions newer WHERE newer.steam_app_id=d.steam_app_id AND newer.id>d.id)"""
        ).fetchone()[0])
        purchased_week = int(connection.execute(
            "SELECT COUNT(*) FROM game_purchases WHERE purchased_on>=? AND purchased_on<?",
            (week_start.date().isoformat(), week_end.date().isoformat()),
        ).fetchone()[0])
        play_rows = connection.execute(
            """SELECT r.play_status,r.rating FROM game_play_reviews r
               WHERE NOT EXISTS (SELECT 1 FROM game_play_reviews newer WHERE newer.steam_app_id=r.steam_app_id AND newer.id>r.id)"""
        ).fetchall()

    playing = sum(1 for row in play_rows if row["play_status"] == "playing")
    evaluation_waiting = sum(1 for row in play_rows if row["play_status"] in {"completed", "stopped"} and row["rating"] == "unrated")
    targets = {key: min(5, count) for key, count in candidate_counts.items()}
    selection_complete = bool(cycle) and all(selection_counts[key] >= targets[key] for key in targets)
    collection_status = "未着手"
    if current_run:
        collection_status = "完了" if str(current_run["status"]) == "success" else "要確認"

    ready = [row for row in records if str(row.get("state")) == "ready"]
    editing = [row for row in records if str(row.get("state")) in {"draft", "review_pending"}]
    next_actions: list[dict[str, str]] = []
    next_actions.extend({"text": item["text"], "url": item["url"], "kind": "要確認"} for item in warnings)
    for row in due_today:
        next_actions.append({"text": f"今日公開予定：{_article_title(row)}", "url": f'/articles/{row["id"]}/edit', "kind": "今日"})
    for row in ready:
        next_actions.append({"text": f"公開前の最終確認：{_article_title(row)}", "url": f'/articles/{row["id"]}/edit', "kind": "記事"})
    for row in sorted(editing, key=lambda item: str(item.get("updated_at") or ""), reverse=True):
        next_actions.append({"text": f"編集を続ける：{_article_title(row)}", "url": f'/articles/{row["id"]}/edit', "kind": "記事"})
    if cycle and not selection_complete:
        missing_new = max(0, targets["new_release"] - selection_counts["new_release"])
        missing_sale = max(0, targets["sale"] - selection_counts["sale"])
        details = "・".join(part for part in (f"新作あと{missing_new}件" if missing_new else "", f"セールあと{missing_sale}件" if missing_sale else "") if part)
        next_actions.append({"text": f"掲載候補を選ぶ（{details}）", "url": "/releases", "kind": "選定"})
    if not current_run:
        next_actions.append({"text": "今週の情報収集を確認する", "url": "/collection", "kind": "収集"})
    if social_pending:
        next_actions.append({"text": f"X投稿案を確認する（{social_pending}件）", "url": "/social", "kind": "X"})

    next_actions = next_actions[:3]
    if warnings:
        overall = "要確認"
    elif not next_actions and (produced or published or current_run):
        overall = "完了"
    elif produced or editing or ready or current_run:
        overall = "進行中"
    else:
        overall = "未着手"

    weekly_picks = [row for row in records if str(row.get("article_type")) == "weekly_picks" and active_this_week(row)]
    weekly_published = [row for row in published if str(row.get("article_type")) == "weekly_picks"]
    return {
        "period": f"{week_start.month}/{week_start.day}〜{(week_end - timedelta(days=1)).month}/{(week_end - timedelta(days=1)).day}",
        "overall": overall,
        "counts": {
            "published": len(published), "editing": len(editing),
            "scheduled": sum(1 for row in records if str(row.get("state")) == "scheduled"),
            "produced": len(produced), "previous_published": len(previous_published),
            "previous_produced": len(previous_produced),
        },
        "warnings": warnings,
        "next_actions": next_actions,
        "articles": weekly_articles,
        "release_flow": {
            "collection": collection_status,
            "selection": f"新作 {selection_counts['new_release']}/{targets['new_release']}・セール {selection_counts['sale']}/{targets['sale']}" if cycle else "候補なし",
            "production": f"編集中 {sum(1 for row in weekly_picks if str(row.get('state')) != 'published')}件",
            "published": f"公開済み {len(weekly_published)}件",
            "social": f"未確認 {social_pending}件" if social_pending else "完了",
        },
        "play": {
            "candidate": play_candidates, "purchased": purchased_week,
            "playing": playing, "evaluation": evaluation_waiting,
        },
    }

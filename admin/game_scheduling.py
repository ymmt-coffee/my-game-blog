"""Phase Jの週次候補収集。承認済み上限内だけを自動実行する。"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from admin import db, editorial_explanations, game_collection, game_information


JST = ZoneInfo("Asia/Tokyo")
WEEKDAY_THURSDAY = 3
SCHEDULED_HOUR = 8


def due_cycle(now: datetime | None = None) -> tuple[str, datetime] | None:
    instant = now or datetime.now(timezone.utc)
    local = instant.astimezone(JST)
    days_since_thursday = (local.weekday() - WEEKDAY_THURSDAY) % 7
    thursday = local.date() - timedelta(days=days_since_thursday)
    due_local = datetime.combine(thursday, time(SCHEDULED_HOUR), JST)
    if local < due_local:
        thursday -= timedelta(days=7)
        due_local = datetime.combine(thursday, time(SCHEDULED_HOUR), JST)
    cycle = thursday.strftime("%G-W%V")
    return cycle, due_local.astimezone(timezone.utc)


def store_collection_result(result: game_collection.CandidateTrialResult, db_path: Path) -> None:
    for item in result.items:
        steam_source = game_information.SourceRecord(
            source_kind="steam", source_name="Steam公開一覧 / Apify",
            url=str(item.game["store_url"]), article_title=str(item.game["title"]),
            candidate_reason="Steamの新作・セール公開一覧から発見",
            discovered_at=str(item.game.get("verified_at") or db.utc_now()),
        ).validated()
        db.save_game_observation(item.game, steam_source, item.price, db_path)
        for media in item.media_items:
            media_source = game_information.SourceRecord(
                source_kind="rss", source_name=media.source_name, url=media.url,
                article_title=media.title, published_at=media.published_at,
                summary=media.summary, candidate_reason="登録媒体で掲載を確認",
                discovered_at=db.utc_now(),
            ).validated()
            db.save_game_observation(item.game, media_source, None, db_path)
        db.save_game_candidate(item.candidate, db_path)


def process_due_weekly_collection(
    db_path: Path,
    *,
    now: datetime | None = None,
    token: str | None = None,
    collector=game_collection.run_weekly_collection,
    ownership_fetcher=game_collection.fetch_owned_games,
) -> str:
    cycle, _due_at = due_cycle(now) or (None, None)
    if not cycle:
        return "not_due"
    run_id = f"scheduled-{cycle}"
    existing = db.get_game_collection_run(run_id, db_path)
    if existing and str(existing.get("status")) in {"success", "partial", "running"}:
        return "already_processed"
    api_token = token if token is not None else game_collection.apify_api_token()
    if not api_token:
        return "credentials_missing"
    if existing:
        failed_at = datetime.fromisoformat(str(existing.get("completed_at") or existing["started_at"]))
        instant = now or datetime.now(timezone.utc)
        if instant - failed_at < timedelta(hours=6):
            return "previous_failure"
        if not db.restart_failed_game_collection_run(run_id, db_path):
            return "previous_failure"
    else:
        db.start_game_collection_run(run_id, "scheduled", game_collection.WEEKLY_STEAM_ITEM_LIMIT, db_path)
    try:
        ownership_failure = ""
        steam_key = game_collection._environment_secret("STEAM_WEB_API_KEY")
        steam_id = game_collection._environment_secret("STEAM_ID64")
        if steam_key and steam_id:
            try:
                owned_games = ownership_fetcher(steam_key, steam_id)
                db.save_owned_games_snapshot(owned_games, db_path)
            except Exception:
                ownership_failure = "Steam所有情報"
        result = collector(api_token, today=date.fromisocalendar(int(cycle[:4]), int(cycle[-2:]), 4))
        store_collection_result(result, db_path)
        media_count = sum(len(item.media_items) for item in result.items)
        explanation_count = 0
        if game_collection._environment_secret("GEMINI_API_KEY"):
            try:
                explanation_count = editorial_explanations.generate(db_path)
            except game_information.GameInformationError:
                explanation_count = 0
        failed_sources = ([ownership_failure] if ownership_failure else []) + list(result.media_failures)
        status = "success" if len(result.items) == game_collection.WEEKLY_STEAM_ITEM_LIMIT and not failed_sources else "partial"
        failure_note = f"（取得失敗: {', '.join(failed_sources)}）" if failed_sources else ""
        db.finish_game_collection_run(
            run_id, status,
            f"週次候補を{len(result.items)}件更新し、媒体掲載{media_count}件を照合、AI説明{explanation_count}件を保存しました。{failure_note}",
            items_discovered=len(result.items), items_stored=len(result.items),
            apify_items=result.apify_items, db_path=db_path,
        )
        return status
    except Exception as exc:
        message = str(exc) if isinstance(exc, game_information.GameInformationError) else "週次候補収集で予期しないエラーが発生しました。"
        db.finish_game_collection_run(run_id, "failure", message, db_path=db_path)
        return "failure"

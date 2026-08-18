"""Phase K AI編集部の固定選定と入力検査。

AI説明はPhase Jで保存済みのものだけを読み、ここでは外部サービスを呼ばない。
購入、記事作成、公開はいずれも利用者の明示操作を必要とする。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


NORMAL_MONTHLY_BUDGET_JPY = 10_000
EXCEPTIONAL_MONTHLY_BUDGET_JPY = 20_000
ARTICLE_TYPES = {"play_note", "weekly_picks", "monthly_essay", "no_article"}
PLAY_STATUSES = {"playing", "completed", "stopped"}
RATINGS = {"good", "neutral", "not_for_me", "unrated"}


class EditorialError(ValueError):
    """利用者へ安全に表示できるAI編集部の入力エラー。"""


def select_top_candidates(rows: list[dict[str, object]], limit: int = 3) -> list[dict[str, object]]:
    """最新周期の有効候補から、新作とセールを可能な範囲で混ぜて選ぶ。"""
    active = [row for row in rows if row.get("status") == "active"]
    if not active:
        return []
    latest_cycle = max(str(row.get("cycle_key") or "") for row in active)
    eligible = [
        row for row in active
        if str(row.get("cycle_key") or "") == latest_cycle and not decision_is_suppressed(row)
    ]
    eligible.sort(key=lambda row: (-int(row.get("total_score") or 0), str(row.get("title") or "").casefold()))
    selected: list[dict[str, object]] = []

    def add_first(kinds: set[str]) -> None:
        for row in eligible:
            if row.get("candidate_kind") in kinds and row not in selected:
                selected.append(row)
                return

    add_first({"new_release"})
    add_first({"sale", "free"})
    for row in eligible:
        if row not in selected:
            selected.append(row)
        if len(selected) >= limit:
            break
    return selected[:limit]


def decision_is_suppressed(row: dict[str, object], now: datetime | None = None) -> bool:
    decision = str(row.get("latest_decision") or "")
    if not decision:
        return False
    if decision == "not_interested":
        return True
    raw = row.get("latest_decision_at")
    if not raw:
        return False
    try:
        decided_at = datetime.fromisoformat(str(raw))
        if decided_at.tzinfo is None:
            decided_at = decided_at.replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    current = now or datetime.now(timezone.utc)
    days = 14 if decision == "hold" else 28
    return current - decided_at < timedelta(days=days)


def suggested_article_type(suitable_for: str | None, candidate_kind: str | None) -> str:
    if suitable_for == "sale_article" or candidate_kind in {"sale", "free"}:
        return "weekly_picks"
    if suitable_for == "article":
        return "monthly_essay"
    if suitable_for == "play":
        return "play_note"
    return "no_article"


def validate_purchase(
    price_jpy: object, exceptional: bool, note: str | None, current_month_total: int = 0,
) -> tuple[int, str | None]:
    try:
        price = int(str(price_jpy).strip())
    except (TypeError, ValueError) as exc:
        raise EditorialError("購入価格は0円以上の整数で入力してください。") from exc
    if price < 0 or price > EXCEPTIONAL_MONTHLY_BUDGET_JPY:
        raise EditorialError("1件の購入価格は例外上限の20,000円以内にしてください。")
    projected = current_month_total + price
    if projected > EXCEPTIONAL_MONTHLY_BUDGET_JPY:
        raise EditorialError("今月の購入合計が例外上限の20,000円を超えるため記録を停止しました。")
    if projected > NORMAL_MONTHLY_BUDGET_JPY and not exceptional:
        raise EditorialError("今月の購入合計が10,000円を超えるため、話題作等の例外として確認してください。")
    cleaned = note.strip() if note else None
    if cleaned and len(cleaned) > 500:
        raise EditorialError("購入メモは500文字以内にしてください。")
    return price, cleaned


def validate_play_review(play_status: str, rating: str, note: str | None) -> tuple[str, str, str | None]:
    if play_status not in PLAY_STATUSES:
        raise EditorialError("プレイ状況が正しくありません。")
    if rating not in RATINGS:
        raise EditorialError("評価が正しくありません。")
    cleaned = note.strip() if note else None
    if cleaned and len(cleaned) > 500:
        raise EditorialError("プレイメモは500文字以内にしてください。")
    return play_status, rating, cleaned


def validate_article_type(value: str) -> str:
    if value not in ARTICLE_TYPES:
        raise EditorialError("記事形式が正しくありません。")
    return value


def current_month() -> str:
    return date.today().strftime("%Y-%m")

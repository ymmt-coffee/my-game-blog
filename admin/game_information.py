"""Phase J共通ゲーム情報の入力検証。外部通信は行わない。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from urllib.parse import urlparse


class GameInformationError(RuntimeError):
    """利用者へ安全に表示できるゲーム情報エラー。"""


def _url(value: str, field_name: str) -> str:
    cleaned = value.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or len(cleaned) > 1000:
        raise GameInformationError(f"{field_name}が正しくありません。")
    return cleaned


def _optional_url(value: str | None, field_name: str) -> str | None:
    return _url(value, field_name) if value and value.strip() else None


def _optional_text(value: str | None, limit: int, field_name: str) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > limit:
        raise GameInformationError(f"{field_name}が長すぎます。")
    return cleaned


def _optional_datetime(value: str | None, field_name: str) -> str | None:
    if not value:
        return None
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise GameInformationError(f"{field_name}が正しくありません。") from exc
    return value


@dataclass(frozen=True)
class GameRecord:
    steam_app_id: str
    title: str
    store_url: str
    japan_availability: str = "unknown"
    japanese_support: str = "unknown"
    single_player: str = "unknown"
    developer: str | None = None
    publisher: str | None = None
    official_url: str | None = None
    release_date: str | None = None
    early_access: bool = False
    free_to_play: bool = False
    review_status: str | None = None
    review_percent: int | None = None
    review_count: int | None = None
    owned: bool | None = None
    wishlisted: bool | None = None
    steam_synced_at: str | None = None
    verified_at: str | None = None

    def validated(self) -> dict[str, object]:
        app_id, title = self.steam_app_id.strip(), self.title.strip()
        if not app_id.isascii() or not app_id.isdigit() or len(app_id) > 20:
            raise GameInformationError("Steam App IDが正しくありません。")
        if not title or len(title) > 300:
            raise GameInformationError("ゲーム名が正しくありません。")
        if self.japan_availability not in {"unknown", "available", "unavailable"}:
            raise GameInformationError("国内販売状態が正しくありません。")
        if self.japanese_support not in {"unknown", "confirmed", "planned", "none"}:
            raise GameInformationError("日本語対応状態が正しくありません。")
        if self.single_player not in {"unknown", "yes", "no"}:
            raise GameInformationError("シングルプレイ状態が正しくありません。")
        if self.review_percent is not None and not 0 <= self.review_percent <= 100:
            raise GameInformationError("レビュー評価が正しくありません。")
        if self.review_count is not None and self.review_count < 0:
            raise GameInformationError("レビュー件数が正しくありません。")
        if self.release_date:
            try:
                date.fromisoformat(self.release_date)
            except ValueError as exc:
                raise GameInformationError("発売日が正しくありません。") from exc
        result = asdict(self)
        result.update({
            "steam_app_id": app_id, "title": title,
            "store_url": _url(self.store_url, "Steam URL"),
            "official_url": _optional_url(self.official_url, "公式URL"),
            "developer": _optional_text(self.developer, 300, "開発元"),
            "publisher": _optional_text(self.publisher, 300, "販売元"),
            "review_status": _optional_text(self.review_status, 100, "レビュー状態"),
            "steam_synced_at": _optional_datetime(self.steam_synced_at, "Steam同期日時"),
            "verified_at": _optional_datetime(self.verified_at, "確認日時"),
        })
        return result


@dataclass(frozen=True)
class SourceRecord:
    source_kind: str
    source_name: str
    url: str
    article_title: str | None = None
    published_at: str | None = None
    summary: str | None = None
    candidate_reason: str | None = None
    discovered_at: str | None = None

    def validated(self) -> dict[str, object]:
        if self.source_kind not in {"rss", "steam", "official", "manual"}:
            raise GameInformationError("情報源の種類が正しくありません。")
        name = _optional_text(self.source_name, 100, "媒体名")
        if not name:
            raise GameInformationError("媒体名を入力してください。")
        result = asdict(self)
        result.update({
            "source_name": name, "url": _url(self.url, "情報源URL"),
            "article_title": _optional_text(self.article_title, 500, "記事タイトル"),
            "summary": _optional_text(self.summary, 1000, "短い要約"),
            "candidate_reason": _optional_text(self.candidate_reason, 500, "候補理由"),
            "published_at": _optional_datetime(self.published_at, "記事公開日時"),
            "discovered_at": _optional_datetime(self.discovered_at, "発見日時"),
        })
        return result


@dataclass(frozen=True)
class PriceRecord:
    currency: str
    source_url: str
    observed_at: str
    regular_price: int | None = None
    current_price: int | None = None
    discount_percent: int | None = None
    sale_ends_at: str | None = None

    def validated(self) -> dict[str, object]:
        if self.currency != "JPY":
            raise GameInformationError("初期版は日本円価格だけを保存します。")
        for amount in (self.regular_price, self.current_price):
            if amount is not None and amount < 0:
                raise GameInformationError("価格が正しくありません。")
        if self.discount_percent is not None and not 0 <= self.discount_percent <= 100:
            raise GameInformationError("割引率が正しくありません。")
        try:
            datetime.fromisoformat(self.observed_at)
            if self.sale_ends_at:
                datetime.fromisoformat(self.sale_ends_at)
        except ValueError as exc:
            raise GameInformationError("価格の確認日時が正しくありません。") from exc
        result = asdict(self)
        result["source_url"] = _url(self.source_url, "価格情報URL")
        return result


@dataclass(frozen=True)
class CandidateRecord:
    id: str
    steam_app_id: str
    cycle_key: str
    candidate_kind: str
    status: str
    interest_score: int
    momentum_score: int
    review_score: int
    price_score: int
    diversity_score: int
    reasons: tuple[str, ...] = ()
    exclusion_reason: str | None = None

    def validated(self) -> dict[str, object]:
        limits = ((self.interest_score, 35), (self.momentum_score, 25),
                  (self.review_score, 15), (self.price_score, 15),
                  (self.diversity_score, 10))
        if any(value < 0 or value > limit for value, limit in limits):
            raise GameInformationError("候補の採点が正しくありません。")
        if self.candidate_kind not in {"editorial", "new_release", "sale", "free", "manual"}:
            raise GameInformationError("候補の種類が正しくありません。")
        if self.status not in {"active", "unconfirmed", "excluded"}:
            raise GameInformationError("候補状態が正しくありません。")
        if not self.cycle_key.strip() or len(self.cycle_key) > 30:
            raise GameInformationError("候補期間が正しくありません。")
        if not self.id.strip() or len(self.id) > 100:
            raise GameInformationError("候補IDが正しくありません。")
        if not self.steam_app_id.isascii() or not self.steam_app_id.isdigit():
            raise GameInformationError("Steam App IDが正しくありません。")
        reasons = tuple(item.strip() for item in self.reasons if item.strip())
        if any(len(item) > 300 for item in reasons) or len(reasons) > 20:
            raise GameInformationError("候補理由が長すぎます。")
        total = sum(value for value, _limit in limits)
        return {
            "id": self.id.strip(), "steam_app_id": self.steam_app_id.strip(),
            "cycle_key": self.cycle_key.strip(), "candidate_kind": self.candidate_kind,
            "status": self.status, "total_score": total,
            "interest_score": self.interest_score, "momentum_score": self.momentum_score,
            "review_score": self.review_score, "price_score": self.price_score,
            "diversity_score": self.diversity_score,
            "reasons_json": json.dumps(reasons, ensure_ascii=False),
            "exclusion_reason": _optional_text(self.exclusion_reason, 500, "除外理由"),
        }

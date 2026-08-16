"""Phase Jの認証前に使う収集・検証部品。外部通信は呼び出し側へ委譲する。"""

from __future__ import annotations

import os
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from admin.game_information import GameInformationError, GameRecord, PriceRecord


MAX_FEED_BYTES = 2 * 1024 * 1024
MAX_FEED_ITEMS = 30
TRIAL_ITEM_LIMIT = 10
WEEKLY_STEAM_ITEM_LIMIT = 20
APIFY_ITEM_LIMIT = 50
APIFY_MONTHLY_BUDGET_USD = 4.0
STEAM_OWNED_GAMES_URL = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
APIFY_ACTOR_ID = "fetch_cat/steam-store-games-scraper"
APIFY_TRIAL_APP_IDS = ("620", "413150", "1245620")
MAX_APIFY_RESPONSE_BYTES = 5 * 1024 * 1024
STEAM_FEATURED_URL = "https://store.steampowered.com/api/featuredcategories?cc=jp&l=japanese"
STEAM_DETAILS_URL = "https://store.steampowered.com/api/appdetails?appids={app_id}&cc=jp&l=japanese"
STEAM_APP_PATTERN = re.compile(
    r"(?:store\.steampowered\.com/(?:agecheck/)?app/|steamcommunity\.com/app/)(\d{1,20})",
    re.IGNORECASE,
)
OFFICIAL_MEDIA_FEEDS = (
    ("4Gamer", "https://www.4gamer.net/rss/index.xml"),
)


@dataclass(frozen=True)
class FeedItem:
    source_name: str
    title: str
    url: str
    published_at: str | None
    summary: str | None
    steam_app_id: str | None


@dataclass(frozen=True)
class CollectionReadiness:
    apify_token: bool
    apify_actor_id: bool
    steam_api_key: bool
    steam_id: bool

    @property
    def trial_ready(self) -> bool:
        return self.apify_token and self.apify_actor_id

    @property
    def ownership_sync_ready(self) -> bool:
        return self.steam_api_key and self.steam_id


@dataclass(frozen=True)
class DiscoveredGame:
    steam_app_id: str
    candidate_kind: str


@dataclass(frozen=True)
class CandidateTrialItem:
    game: dict[str, object]
    price: dict[str, object] | None
    candidate: dict[str, object]
    media_items: tuple[FeedItem, ...] = ()


@dataclass(frozen=True)
class CandidateTrialResult:
    items: tuple[CandidateTrialItem, ...]
    apify_items: int
    media_failures: tuple[str, ...] = ()


def collection_readiness(environment: dict[str, str] | None = None) -> CollectionReadiness:
    values = os.environ if environment is None else environment
    return CollectionReadiness(
        apify_token=bool(apify_api_token(environment)),
        apify_actor_id=True,
        steam_api_key=bool(_environment_secret("STEAM_WEB_API_KEY", environment)),
        steam_id=bool(_environment_secret("STEAM_ID64", environment)),
    )


def apify_api_token(environment: dict[str, str] | None = None) -> str:
    return _environment_secret("APIFY_API_TOKEN", environment)


def _environment_secret(name: str, environment: dict[str, str] | None = None) -> str:
    values = os.environ if environment is None else environment
    token = values.get(name, "").strip()
    if token or environment is not None or os.name != "nt":
        return token
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _kind = winreg.QueryValueEx(key, name)
        return str(value).strip()
    except (FileNotFoundError, OSError):
        return ""


def extract_steam_app_id(*values: str | None) -> str | None:
    for value in values:
        match = STEAM_APP_PATTERN.search(value or "")
        if match:
            return match.group(1)
    return None


def _clean_text(value: str | None, limit: int) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"<[^>]+>", " ", unescape(value))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:limit] or None


def _child_text(element: ET.Element, names: tuple[str, ...]) -> str | None:
    for child in element:
        name = child.tag.rsplit("}", 1)[-1].lower()
        if name in names and child.text:
            return child.text.strip()
    return None


def parse_feed(payload: bytes, source_name: str, item_limit: int = MAX_FEED_ITEMS) -> list[FeedItem]:
    if not payload or len(payload) > MAX_FEED_BYTES:
        raise GameInformationError("RSSのデータ量が上限を超えています。")
    if item_limit < 1 or item_limit > MAX_FEED_ITEMS:
        raise GameInformationError("RSSの取得件数が正しくありません。")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise GameInformationError("RSSの形式を確認できませんでした。") from exc
    entries = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1].lower() in {"item", "entry"}]
    results: list[FeedItem] = []
    for entry in entries[:item_limit]:
        title = _clean_text(_child_text(entry, ("title",)), 500)
        link = _child_text(entry, ("link",))
        if not link:
            for child in entry:
                if child.tag.rsplit("}", 1)[-1].lower() == "link" and child.attrib.get("href"):
                    link = child.attrib["href"].strip()
                    break
        parsed = urlparse(link or "")
        if not title or parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        summary = _clean_text(_child_text(entry, ("description", "summary", "content")), 1000)
        published = _iso_feed_datetime(_clean_text(
            _child_text(entry, ("pubdate", "published", "updated", "date")), 100
        ))
        results.append(FeedItem(
            source_name=source_name, title=title, url=link or "", published_at=published,
            summary=summary, steam_app_id=extract_steam_app_id(link, summary, title),
        ))
    return results


def fetch_feed(url: str, source_name: str, transport=None) -> list[FeedItem]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise GameInformationError("RSSの接続先が正しくありません。")
    request = Request(url, headers={"User-Agent": "my-game-blog-local-admin/1.0"})
    try:
        payload = (transport or _open_request)(request, 30)
    except Exception as exc:
        raise GameInformationError(f"{source_name}のRSS取得に失敗しました。") from exc
    return parse_feed(payload, source_name)


def _match_text(value: object) -> str:
    return re.sub(r"[^0-9a-z\u3040-\u30ff\u3400-\u9fff]+", "", str(value or "").casefold())


def match_media_items(title: str, items: list[FeedItem]) -> tuple[FeedItem, ...]:
    """記事本文を取得せず、RSS内の見出し・短い要約だけで既存候補へ対応付ける。"""
    needle = _match_text(title)
    if len(needle) < 4:
        return ()
    matched: list[FeedItem] = []
    for item in items:
        haystack = _match_text(f"{item.title} {item.summary or ''}")
        if needle in haystack:
            matched.append(item)
    return tuple(matched[:5])


def add_media_momentum(
    trial: CandidateTrialResult,
    feed_items: list[FeedItem],
) -> CandidateTrialResult:
    """媒体掲載を話題性へ加える。固定配点25点を超えず、事実判定には使わない。"""
    enriched: list[CandidateTrialItem] = []
    for item in trial.items:
        matched = match_media_items(str(item.game.get("title") or ""), feed_items)
        candidate = dict(item.candidate)
        if matched:
            sources = sorted({entry.source_name for entry in matched})
            candidate["momentum_score"] = min(25, int(candidate["momentum_score"]) + 5 * len(sources))
            raw_reasons = candidate.get("reasons_json")
            try:
                reasons = list(json.loads(str(raw_reasons))) if raw_reasons else []
            except (TypeError, ValueError, json.JSONDecodeError):
                reasons = []
            reasons.append(f"{', '.join(sources)}掲載を話題性に加点")
            candidate["reasons_json"] = reasons
            from admin.game_information import CandidateRecord
            candidate = CandidateRecord(
                id=str(candidate["id"]), steam_app_id=str(candidate["steam_app_id"]),
                cycle_key=str(candidate["cycle_key"]), candidate_kind=str(candidate["candidate_kind"]),
                status=str(candidate["status"]), interest_score=int(candidate["interest_score"]),
                momentum_score=int(candidate["momentum_score"]), review_score=int(candidate["review_score"]),
                price_score=int(candidate["price_score"]), diversity_score=int(candidate["diversity_score"]),
                reasons=tuple(str(reason) for reason in reasons),
                exclusion_reason=str(candidate["exclusion_reason"]) if candidate.get("exclusion_reason") else None,
            ).validated()
        enriched.append(CandidateTrialItem(item.game, item.price, candidate, matched))
    return CandidateTrialResult(tuple(enriched), trial.apify_items, trial.media_failures)


def run_weekly_collection(
    token: str,
    *,
    featured_transport=None,
    apify_transport=None,
    steam_transport=None,
    feed_transport=None,
    usage_transport=None,
    today: date | None = None,
    item_limit: int = WEEKLY_STEAM_ITEM_LIMIT,
) -> CandidateTrialResult:
    usage = apify_monthly_usage_usd(token, usage_transport)
    if usage >= APIFY_MONTHLY_BUDGET_USD:
        raise GameInformationError("Apifyの月間利用上限に達したため、週次収集を停止しました。")
    trial = run_candidate_trial(
        token, featured_transport=featured_transport, apify_transport=apify_transport,
        steam_transport=steam_transport, today=today, item_limit=item_limit,
    )
    media: list[FeedItem] = []
    failures: list[str] = []
    for source_name, url in OFFICIAL_MEDIA_FEEDS:
        try:
            media.extend(fetch_feed(url, source_name, feed_transport))
        except GameInformationError:
            # 一媒体の失敗でSteam候補を失わない。呼び出し側は件数から部分成功を表示する。
            failures.append(source_name)
    with_failures = CandidateTrialResult(trial.items, trial.apify_items, tuple(failures))
    return add_media_momentum(with_failures, media)


def apify_monthly_usage_usd(token: str, transport=None) -> float:
    request = Request(
        "https://api.apify.com/v2/users/me/usage/monthly",
        headers={"Authorization": f"Bearer {token.strip()}", "User-Agent": "my-game-blog-local-admin/1.0"},
    )
    payload = _load_json_response(request, 30, transport, "Apify月間利用額")
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise GameInformationError("Apifyの月間利用額を確認できませんでした。")
    value = data.get("totalUsageCreditsUsdAfterVolumeDiscount")
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise GameInformationError("Apifyの月間利用額を確認できませんでした。")
    return float(value)


def fetch_owned_games(api_key: str, steam_id: str, transport=None) -> list[dict[str, object]]:
    """Steamの正式APIから所有App IDと名称だけを取得する。キーはURLへ含めない。"""
    cleaned_key, cleaned_id = api_key.strip(), steam_id.strip()
    if not cleaned_key or not cleaned_id.isascii() or not cleaned_id.isdigit() or not 16 <= len(cleaned_id) <= 20:
        raise GameInformationError("Steam所有情報の認証設定が正しくありません。")
    query = urlencode({
        "input_json": json.dumps({
            "steamid": cleaned_id,
            "include_appinfo": True,
            "include_played_free_games": True,
        }, separators=(",", ":")),
    })
    request = Request(f"{STEAM_OWNED_GAMES_URL}?{query}", method="GET", headers={
        "x-webapi-key": cleaned_key,
        "User-Agent": "my-game-blog-local-admin/1.0",
    })
    payload = _load_json_response(request, 60, transport, "Steam所有ゲーム")
    response = payload.get("response") if isinstance(payload, dict) else None
    games = response.get("games") if isinstance(response, dict) else None
    if not isinstance(games, list) or len(games) > 20_000:
        raise GameInformationError("Steam所有ゲームの応答形式を確認できませんでした。")
    synced_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in games:
        if not isinstance(item, dict):
            raise GameInformationError("Steam所有ゲームの応答形式を確認できませんでした。")
        app_id, title = str(item.get("appid") or ""), str(item.get("name") or "").strip()
        if app_id in seen:
            continue
        record = GameRecord(
            steam_app_id=app_id,
            title=title,
            store_url=f"https://store.steampowered.com/app/{app_id}/?cc=jp&l=japanese",
            owned=True,
            steam_synced_at=synced_at,
        ).validated()
        result.append(record)
        seen.add(app_id)
    return result


def parse_steam_store_response(app_id: str, payload: object, observed_at: str | None = None) -> tuple[dict[str, object], dict[str, object] | None]:
    if not isinstance(payload, dict) or not isinstance(payload.get(app_id), dict):
        raise GameInformationError("Steam情報の形式を確認できませんでした。")
    envelope = payload[app_id]
    data = envelope.get("data") if envelope.get("success") is True else None
    if not isinstance(data, dict) or str(data.get("steam_appid")) != app_id:
        raise GameInformationError("Steamで対象ゲームを確認できませんでした。")
    categories = data.get("categories") if isinstance(data.get("categories"), list) else []
    category_names = " ".join(str(item.get("description", "")) for item in categories if isinstance(item, dict)).lower()
    languages = str(data.get("supported_languages", "")).lower()
    release = data.get("release_date") if isinstance(data.get("release_date"), dict) else {}
    price_overview = data.get("price_overview") if isinstance(data.get("price_overview"), dict) else None
    game = GameRecord(
        steam_app_id=app_id,
        title=str(data.get("name") or ""),
        store_url=f"https://store.steampowered.com/app/{app_id}/?cc=jp&l=japanese",
        japan_availability="available",
        japanese_support="confirmed" if "japanese" in languages or "日本語" in languages else "none",
        single_player="yes" if "single-player" in category_names or "シングルプレイヤー" in category_names else "unknown",
        developer=", ".join(str(item) for item in data.get("developers", [])[:5]) if isinstance(data.get("developers"), list) else None,
        publisher=", ".join(str(item) for item in data.get("publishers", [])[:5]) if isinstance(data.get("publishers"), list) else None,
        official_url=str(data.get("website") or "") or None,
        release_date=_iso_release_date(str(release.get("date") or "")),
        early_access=False,
        free_to_play=bool(data.get("is_free")),
        verified_at=observed_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    ).validated()
    price = None
    if price_overview:
        currency = str(price_overview.get("currency") or "")
        price = PriceRecord(
            currency=currency,
            regular_price=_steam_price_amount(price_overview.get("initial"), currency),
            current_price=_steam_price_amount(price_overview.get("final"), currency),
            discount_percent=_integer(price_overview.get("discount_percent")),
            source_url=str(game["store_url"]),
            observed_at=observed_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ).validated()
    return game, price


def _integer(value: object) -> int | None:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def _steam_price_amount(value: object, currency: str) -> int | None:
    amount = _integer(value)
    if amount is None:
        return None
    # Steam appdetailsはJPYも小数通貨と同じ100倍の整数で返す。
    return amount // 100 if currency == "JPY" else amount


def _iso_release_date(value: str) -> str | None:
    for pattern in ("%d %b, %Y", "%b %d, %Y", "%Y年%m月%d日"):
        try:
            return datetime.strptime(value.strip(), pattern).date().isoformat()
        except ValueError:
            continue
    return None


def _iso_feed_datetime(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat(timespec="seconds")


def trial_items(items: list[object], limit: int = TRIAL_ITEM_LIMIT) -> list[object]:
    if limit < 1 or limit > TRIAL_ITEM_LIMIT:
        raise GameInformationError("試運転は最大10件です。")
    return items[:limit]


def parse_featured_candidates(payload: object, limit: int = TRIAL_ITEM_LIMIT) -> list[DiscoveredGame]:
    if limit < 1 or limit > WEEKLY_STEAM_ITEM_LIMIT or not isinstance(payload, dict):
        raise GameInformationError("Steam候補一覧の形式を確認できませんでした。")
    results: list[DiscoveredGame] = []
    seen: set[str] = set()
    new_limit = min(10, (limit + 1) // 2)
    sale_limit = min(10, limit - new_limit)
    sections = (("new_releases", "new_release", new_limit), ("specials", "sale", sale_limit))
    for section_name, candidate_kind, section_limit in sections:
        section = payload.get(section_name)
        items = section.get("items") if isinstance(section, dict) else None
        if not isinstance(items, list):
            continue
        added = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            app_id = str(item.get("id") or "")
            if not app_id.isascii() or not app_id.isdigit() or app_id in seen:
                continue
            if candidate_kind == "sale" and _integer(item.get("discount_percent")) in {None, 0}:
                continue
            results.append(DiscoveredGame(app_id, candidate_kind))
            seen.add(app_id)
            added += 1
            if added >= section_limit or len(results) >= limit:
                break
    if not results:
        raise GameInformationError("Steamから試運転候補を取得できませんでした。")
    return results[:limit]


def run_candidate_trial(token: str, *, featured_transport=None, apify_transport=None, steam_transport=None,
                        today: date | None = None, item_limit: int = TRIAL_ITEM_LIMIT) -> CandidateTrialResult:
    featured_request = Request(STEAM_FEATURED_URL, headers={"User-Agent": "my-game-blog-local-admin/1.0"})
    featured_payload = _load_json_response(featured_request, 30, featured_transport, "Steam候補一覧")
    discovered = parse_featured_candidates(featured_payload, item_limit)
    apify_results = run_apify_trial(token, tuple(item.steam_app_id for item in discovered), apify_transport)
    apify_by_id = {str(game["steam_app_id"]): (game, price) for game, price in apify_results}
    cycle_key = (today or datetime.now(timezone.utc).date()).strftime("%G-W%V")
    results: list[CandidateTrialItem] = []
    for item in discovered:
        request = Request(STEAM_DETAILS_URL.format(app_id=item.steam_app_id), headers={
            "User-Agent": "my-game-blog-local-admin/1.0",
        })
        payload = _load_json_response(request, 30, steam_transport, "Steam詳細情報")
        game, price = parse_steam_store_response(item.steam_app_id, payload)
        apify_game, apify_price = apify_by_id.get(item.steam_app_id, ({}, None))
        for field in ("review_status", "review_percent", "review_count"):
            if apify_game.get(field) is not None:
                game[field] = apify_game[field]
        if price is None:
            price = apify_price
        tags = _steam_classification_text(item.steam_app_id, payload)
        candidate = score_candidate(game, price, item.candidate_kind, cycle_key, tags, today=today)
        results.append(CandidateTrialItem(game, price, candidate))
    return CandidateTrialResult(tuple(results), len(apify_results))


def score_candidate(game: dict[str, object], price: dict[str, object] | None, candidate_kind: str,
                    cycle_key: str, classification_text: str = "", *, today: date | None = None) -> dict[str, object]:
    from admin.game_information import CandidateRecord

    status, exclusion = "active", None
    reasons: list[str] = []
    lowered = classification_text.lower()
    if "horror" in lowered or "ホラー" in lowered:
        status, exclusion = "excluded", "主要ジャンルがホラーです。"
    elif game.get("japanese_support") == "none":
        status, exclusion = "excluded", "日本語対応を確認できません。"
    elif game.get("single_player") == "no":
        status, exclusion = "excluded", "シングルプレイ作品ではありません。"
    elif game.get("japanese_support") != "confirmed" or game.get("single_player") != "yes":
        status, exclusion = "unconfirmed", "日本語対応またはシングルプレイ対応の確認が必要です。"

    review_percent = game.get("review_percent") if isinstance(game.get("review_percent"), int) else None
    review_count = game.get("review_count") if isinstance(game.get("review_count"), int) else 0
    if status != "excluded" and review_percent is not None and review_percent < 40 and review_count >= 20:
        status, exclusion = "excluded", "Steam評価が不評以下です。"

    current_price = price.get("current_price") if price and isinstance(price.get("current_price"), int) else None
    discount = price.get("discount_percent") if price and isinstance(price.get("discount_percent"), int) else 0
    if status != "excluded" and current_price is not None and current_price > 20000:
        status, exclusion = "excluded", "例外予算の2万円を超えています。"
    if status != "excluded" and candidate_kind == "sale" and discount < 20:
        status, exclusion = "excluded", "通常候補の割引率20%に達していません。"

    release_date = game.get("release_date")
    reference = today or datetime.now(timezone.utc).date()
    if status != "excluded" and candidate_kind == "new_release" and isinstance(release_date, str):
        released = date.fromisoformat(release_date)
        if not reference - timedelta(days=14) <= released <= reference + timedelta(days=30):
            status, exclusion = "excluded", "新作候補の発売日前後期間から外れています。"

    interest = 35 if game.get("wishlisted") else 0
    momentum = 15 if candidate_kind == "new_release" else 10
    review = 15 if review_percent is not None and review_percent >= 90 and review_count >= 100 else (
        12 if review_percent is not None and review_percent >= 80 else 8 if review_percent is not None and review_percent >= 70 else 0
    )
    price_score = 15 if game.get("free_to_play") or discount >= 50 else 12 if discount >= 30 else 10 if discount >= 20 else (
        5 if current_price is not None and current_price <= 10000 else 0
    )
    diversity = 10
    reasons.extend(("Steam新作一覧から発見" if candidate_kind == "new_release" else "Steamセール一覧から発見",))
    if review:
        reasons.append("Steamレビューを加点")
    if price_score:
        reasons.append("価格・割引を加点")
    return CandidateRecord(
        id=f"{cycle_key}-{game['steam_app_id']}-{candidate_kind}", steam_app_id=str(game["steam_app_id"]),
        cycle_key=cycle_key, candidate_kind=candidate_kind, status=status,
        interest_score=interest, momentum_score=momentum, review_score=review,
        price_score=price_score, diversity_score=diversity, reasons=tuple(reasons),
        exclusion_reason=exclusion,
    ).validated()


def _steam_classification_text(app_id: str, payload: object) -> str:
    envelope = payload.get(app_id) if isinstance(payload, dict) else None
    data = envelope.get("data") if isinstance(envelope, dict) else None
    if not isinstance(data, dict):
        return ""
    values: list[str] = []
    for field in ("genres", "categories"):
        entries = data.get(field)
        if isinstance(entries, list):
            values.extend(str(entry.get("description") or "") for entry in entries if isinstance(entry, dict))
    return " ".join(values)


def _load_json_response(request: Request, timeout: int, transport, label: str) -> object:
    try:
        response_bytes = (transport or _open_request)(request, timeout)
        if len(response_bytes) > MAX_APIFY_RESPONSE_BYTES:
            raise GameInformationError(f"{label}の応答サイズが上限を超えました。")
        return json.loads(response_bytes.decode("utf-8"))
    except GameInformationError:
        raise
    except Exception as exc:
        raise GameInformationError(f"{label}の取得または応答確認に失敗しました。") from exc


def parse_apify_item(item: object) -> tuple[dict[str, object], dict[str, object] | None]:
    if not isinstance(item, dict) or item.get("success") is not True:
        raise GameInformationError("Apifyのゲーム情報を確認できませんでした。")
    app_id = str(item.get("appId") or "")
    categories = item.get("categories") if isinstance(item.get("categories"), list) else []
    category_text = " ".join(str(value) for value in categories).lower()
    positive, negative = _integer(item.get("totalPositiveReviews")), _integer(item.get("totalNegativeReviews"))
    review_count = (positive + negative) if positive is not None and negative is not None else None
    review_percent = round(positive * 100 / review_count) if positive is not None and review_count else None
    observed_at = str(item.get("scrapedAt") or "")
    game = GameRecord(
        steam_app_id=app_id, title=str(item.get("name") or ""),
        store_url=str(item.get("url") or f"https://store.steampowered.com/app/{app_id}/"),
        japan_availability="available" if item.get("currency") == "JPY" else "unknown",
        japanese_support="unknown",
        single_player="yes" if "single" in category_text or "シングルプレイヤー" in category_text else "unknown",
        developer=_joined(item.get("developers")), publisher=_joined(item.get("publishers")),
        official_url=str(item.get("website") or "") or None,
        release_date=_iso_release_date(str(item.get("releaseDate") or "")),
        early_access="early access" in category_text or "早期アクセス" in category_text,
        free_to_play=bool(item.get("isFree")), review_status=_optional_string(item.get("reviewScoreDescription")),
        review_percent=review_percent, review_count=review_count, verified_at=observed_at or None,
    ).validated()
    price = None
    if item.get("currency") == "JPY":
        price = PriceRecord(
            currency="JPY", regular_price=_integer(item.get("initialPrice")),
            current_price=_integer(item.get("price")), discount_percent=_integer(item.get("discountPercent")),
            source_url=str(game["store_url"]), observed_at=observed_at,
        ).validated()
    return game, price


def run_apify_trial(
    token: str, app_ids: tuple[str, ...] = APIFY_TRIAL_APP_IDS,
    transport=None,
) -> list[tuple[dict[str, object], dict[str, object] | None]]:
    cleaned_token = token.strip()
    if not cleaned_token:
        raise GameInformationError("Apify APIトークンが設定されていません。")
    if not app_ids or len(app_ids) > APIFY_ITEM_LIMIT or any(not value.isdigit() for value in app_ids):
        raise GameInformationError("Apifyの対象件数またはSteam App IDが正しくありません。")
    actor_path = APIFY_ACTOR_ID.replace("/", "~")
    url = f"https://api.apify.com/v2/acts/{actor_path}/run-sync-get-dataset-items?timeout=120"
    body = json.dumps({
        "searchTerms": [], "appIds": list(app_ids), "maxItems": len(app_ids),
        "country": "JP", "language": "japanese", "includeDescriptions": False,
        "includeScreenshots": False, "includeDlc": False, "includeReviewsSummary": True,
    }).encode("utf-8")
    request = Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {cleaned_token}", "Content-Type": "application/json",
        "User-Agent": "my-game-blog-local-admin/1.0",
    })
    try:
        response_bytes = (transport or _open_request)(request, 150)
        if len(response_bytes) > MAX_APIFY_RESPONSE_BYTES:
            raise GameInformationError("Apifyの応答サイズが上限を超えました。")
        payload = json.loads(response_bytes.decode("utf-8"))
    except GameInformationError:
        raise
    except Exception as exc:
        raise GameInformationError("Apifyへの接続または応答確認に失敗しました。") from exc
    if not isinstance(payload, list) or len(payload) > len(app_ids):
        raise GameInformationError("Apifyの応答件数を確認できませんでした。")
    return [parse_apify_item(item) for item in payload]


def _open_request(request: Request, timeout: int) -> bytes:
    with urlopen(request, timeout=timeout) as response:
        return response.read(MAX_APIFY_RESPONSE_BYTES + 1)


def _joined(value: object) -> str | None:
    if not isinstance(value, list):
        return None
    result = ", ".join(str(item) for item in value[:5] if str(item).strip())
    return result or None


def _optional_string(value: object) -> str | None:
    return str(value).strip() if value is not None and str(value).strip() else None

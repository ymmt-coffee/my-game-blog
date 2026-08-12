"""個人情報を持たない集計済みアクセス解析CSVの取込と比較。"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo


MAX_CSV_BYTES = 2 * 1024 * 1024
MAX_ROWS = 10_000
REQUIRED_COLUMNS = {"date", "path", "views", "visitors"}
UMAMI_COLUMNS = {"website_id", "session_id", "event_type", "hostname", "url_path", "created_at"}
UMAMI_HOSTNAME = "ymmt-coffee.github.io"
UMAMI_PATH_PREFIX = "/my-game-blog"
JST = ZoneInfo("Asia/Tokyo")


class AnalyticsError(ValueError):
    pass


def parse_csv(data: bytes) -> list[dict[str, object]]:
    if not data:
        raise AnalyticsError("CSVファイルが空です。")
    if len(data) > MAX_CSV_BYTES:
        raise AnalyticsError("CSVファイルは2MB以下にしてください。")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AnalyticsError("CSVはUTF-8形式で保存してください。") from exc
    reader = csv.DictReader(io.StringIO(text))
    columns = {str(item or "").strip().casefold() for item in (reader.fieldnames or [])}
    if not REQUIRED_COLUMNS.issubset(columns):
        raise AnalyticsError("CSVにはdate、path、views、visitors列が必要です。")
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for number, raw in enumerate(reader, start=2):
        if len(rows) >= MAX_ROWS:
            raise AnalyticsError("CSVは10,000行以下にしてください。")
        normalized = {str(key or "").strip().casefold(): str(value or "").strip() for key, value in raw.items()}
        try:
            day = date.fromisoformat(normalized["date"]).isoformat()
            views = int(normalized["views"])
            visitors = int(normalized["visitors"])
        except (ValueError, KeyError) as exc:
            raise AnalyticsError(f"CSVの{number}行目に正しくない日付または数値があります。") from exc
        path = normalized.get("path", "")
        if not path.startswith("/") or "?" in path or "#" in path or len(path) > 500:
            raise AnalyticsError(f"CSVの{number}行目のページパスが正しくありません。")
        if views < 0 or visitors < 0:
            raise AnalyticsError(f"CSVの{number}行目に負の数値があります。")
        key = (day, path)
        if key in seen:
            raise AnalyticsError(f"CSVの{number}行目に同じ日付とページの重複があります。")
        seen.add(key)
        rows.append({"day": day, "path": path, "views": views, "visitors": visitors})
    if not rows:
        raise AnalyticsError("CSVにデータ行がありません。")
    return rows


def _decode_csv(data: bytes) -> tuple[str, set[str]]:
    if not data:
        raise AnalyticsError("CSVファイルが空です。")
    if len(data) > MAX_CSV_BYTES:
        raise AnalyticsError("CSVファイルは2MB以下にしてください。")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AnalyticsError("CSVはUTF-8形式で保存してください。") from exc
    reader = csv.DictReader(io.StringIO(text))
    columns = {str(item or "").strip().casefold() for item in (reader.fieldnames or [])}
    return text, columns


def parse_umami_export(data: bytes) -> list[dict[str, object]]:
    """Umamiのwebsite_event.csvを匿名の日別・ページ別集計へ変換する。"""
    text, columns = _decode_csv(data)
    if not UMAMI_COLUMNS.issubset(columns):
        raise AnalyticsError("Umamiのwebsite_event.csvを選択してください。")
    grouped: dict[tuple[str, str], dict[str, object]] = {}
    reader = csv.DictReader(io.StringIO(text))
    for number, raw in enumerate(reader, start=2):
        if number - 1 > MAX_ROWS:
            raise AnalyticsError("CSVは10,000行以下にしてください。")
        normalized = {str(key or "").strip().casefold(): str(value or "").strip() for key, value in raw.items()}
        if normalized.get("event_type") != "1":
            continue
        if normalized.get("hostname") != UMAMI_HOSTNAME:
            raise AnalyticsError(f"CSVの{number}行目に対象外のホストがあります。")
        raw_path = normalized.get("url_path", "")
        if raw_path != UMAMI_PATH_PREFIX and not raw_path.startswith(f"{UMAMI_PATH_PREFIX}/"):
            raise AnalyticsError(f"CSVの{number}行目に対象外のページパスがあります。")
        path = raw_path[len(UMAMI_PATH_PREFIX):] or "/"
        if not path.startswith("/") or "?" in path or "#" in path or len(path) > 500:
            raise AnalyticsError(f"CSVの{number}行目のページパスが正しくありません。")
        session_id = normalized.get("session_id", "")
        if not session_id:
            raise AnalyticsError(f"CSVの{number}行目にセッション識別子がありません。")
        try:
            instant = datetime.fromisoformat(normalized.get("created_at", "").replace(" ", "T"))
        except ValueError as exc:
            raise AnalyticsError(f"CSVの{number}行目の日時が正しくありません。") from exc
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
        day = instant.astimezone(JST).date().isoformat()
        item = grouped.setdefault((day, path), {"day": day, "path": path, "views": 0, "sessions": set()})
        item["views"] = int(item["views"]) + 1
        sessions = item["sessions"]
        if isinstance(sessions, set):
            sessions.add(session_id)
    if not grouped:
        raise AnalyticsError("Umami CSVにページ表示データがありません。")
    return [
        {"day": item["day"], "path": item["path"], "views": item["views"], "visitors": len(item["sessions"])}
        for item in sorted(grouped.values(), key=lambda value: (str(value["day"]), str(value["path"])))
    ]


def parse_import(data: bytes) -> tuple[list[dict[str, object]], str]:
    """列構成からUmami実データまたは従来の集計済みCSVを判別する。"""
    _text, columns = _decode_csv(data)
    if UMAMI_COLUMNS.issubset(columns):
        return parse_umami_export(data), "umami"
    return parse_csv(data), "manual"


def period(days: int, *, today: date | None = None) -> tuple[date, date, date, date]:
    end = today or date.today()
    start = end - timedelta(days=days - 1)
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=days - 1)
    return start, end, previous_start, previous_end


def change_percent(current: int, previous: int) -> str:
    if previous == 0:
        return "—" if current == 0 else "新規"
    value = (current - previous) * 100 / previous
    return f"{value:+.1f}%"


def suggestions(current: dict[str, object], previous: dict[str, object]) -> list[str]:
    views = int(current["views"])
    prior = int(previous["views"])
    pages = list(current["pages"])
    if views == 0:
        return ["データを取り込むと、期間比較とよく読まれた記事を確認できます。"]
    result: list[str] = []
    if prior and views < prior * 0.8:
        result.append("閲覧数が直前期間より20%以上減っています。更新頻度やトップページからの記事導線を確認してください。")
    if pages and int(pages[0]["views"]) >= views * 0.5:
        result.append("閲覧が上位1ページへ集中しています。その記事から関連する記事へのリンク追加を検討できます。")
    if not result:
        result.append("大きな減少や極端な記事集中は見つかりませんでした。期間を切り替えて傾向を確認してください。")
    return result


TEMPLATE = "date,path,views,visitors\n2026-08-11,/posts/example/,10,8\n"

"""個人情報を持たない集計済みアクセス解析CSVの取込と比較。"""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta


MAX_CSV_BYTES = 2 * 1024 * 1024
MAX_ROWS = 10_000
REQUIRED_COLUMNS = {"date", "path", "views", "visitors"}
ALLOWED_SOURCES = {"manual", "umami", "google", "plausible"}


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

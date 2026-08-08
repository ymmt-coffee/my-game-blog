#!/usr/bin/env python3
"""Phase 5: validate manually entered weekly game candidates and build a safe draft."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo


JST = ZoneInfo("Asia/Tokyo")
STEAM_HOSTS = {"store.steampowered.com"}
KINDS = {"release", "sale"}
LANGUAGE_KEYS = {"interface", "subtitles", "full_audio"}
AI_ITEM_KEYS = {"app_id", "facts_sha256", "official_summary", "editorial_reason"}
SAFE_WEEK = re.compile(r"\d{4}-W\d{2}")
ATTENTION_REASONS = {"candidate_shortage", "source_missing", "source_conflict", "release_delayed", "price_changed", "duplicate", "validation_failed"}
ERROR_REASONS = {"network_failed", "save_failed", "lock_failed", "unexpected_failure"}


class WeeklyPicksError(RuntimeError):
    """Safe validation error that never includes free-form article text."""


@dataclass(frozen=True)
class WeekWindow:
    week_id: str
    monday: date
    sunday: date


def week_window(value: datetime | date) -> WeekWindow:
    local_date = value.astimezone(JST).date() if isinstance(value, datetime) else value
    monday = local_date - timedelta(days=local_date.weekday())
    iso = monday.isocalendar()
    return WeekWindow(f"{iso.year:04d}-W{iso.week:02d}", monday, monday + timedelta(days=6))


def sunday_deadline(window: WeekWindow) -> datetime:
    """Sunday 24:00 is the following Monday 00:00 in JST."""
    return datetime.combine(window.sunday + timedelta(days=1), time.min, JST)


def normalize_url(raw: str) -> str:
    parsed = urlsplit(str(raw).strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise WeeklyPicksError("URLはhttpsの絶対URLで入力してください")
    host = parsed.hostname.lower()
    port = f":{parsed.port}" if parsed.port else ""
    path = re.sub(r"/+", "/", parsed.path).rstrip("/") or "/"
    return urlunsplit(("https", host + port, path, "", ""))


def steam_app_id(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.hostname not in STEAM_HOSTS:
        raise WeeklyPicksError("Steam URLはstore.steampowered.comの公式ページに限ります")
    match = re.fullmatch(r"/app/(\d+)(?:/[^/]*)?", parsed.path)
    if not match:
        raise WeeklyPicksError("Steam URLからApp IDを確認できません")
    return match.group(1)


def parse_verified_at(raw: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(raw))
    except ValueError as exc:
        raise WeeklyPicksError("確認日時はタイムゾーン付きISO形式で入力してください") from exc
    if parsed.tzinfo is None:
        raise WeeklyPicksError("確認日時にはタイムゾーンが必要です")
    return parsed


def calculated_discount(original: int, current: int) -> int:
    if original <= 0 or current <= 0 or current >= original:
        raise WeeklyPicksError("セール価格は通常価格より小さい正の整数にしてください")
    return round((original - current) * 100 / original)


def assert_safe_text(value: str, label: str) -> None:
    lowered = value.casefold()
    unsafe = (
        "<script", "javascript:", "discord.com/api/webhooks/", "discordapp.com/api/webhooks/",
        "api_key=", "apikey=", "token=", "authorization: bearer", "-----begin private key-----",
    )
    if any(marker in lowered for marker in unsafe) or any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise WeeklyPicksError(f"{label}に秘密情報または危険な文字列の疑いがあります。値は表示しません")


def _required(candidate: dict[str, Any], key: str) -> Any:
    value = candidate.get(key)
    if value is None or value == "":
        raise WeeklyPicksError(f"候補の必須項目がありません: {key}")
    return value


def validate_candidate(candidate: dict[str, Any], window: WeekWindow) -> dict[str, Any]:
    kind = str(_required(candidate, "kind"))
    if kind not in KINDS:
        raise WeeklyPicksError("kindはreleaseまたはsaleにしてください")
    url = normalize_url(str(_required(candidate, "steam_url")))
    app_id = str(_required(candidate, "app_id"))
    if app_id != steam_app_id(url):
        raise WeeklyPicksError("入力したApp IDとSteam URLが一致しません")
    title = str(_required(candidate, "title")).strip()
    if len(title) > 160 or "\n" in title or "\r" in title:
        raise WeeklyPicksError("作品名が長すぎるか改行を含んでいます")
    assert_safe_text(title, "作品名")
    try:
        release_date = date.fromisoformat(str(_required(candidate, "release_date")))
    except ValueError as exc:
        raise WeeklyPicksError("発売日はYYYY-MM-DDで入力してください") from exc
    if kind == "release" and not (window.monday <= release_date <= window.sunday):
        raise WeeklyPicksError("新作候補の発売日が対象週外です")
    if candidate.get("region") != "JP" or candidate.get("currency") != "JPY":
        raise WeeklyPicksError("地域JP・通貨JPYを確認できない候補は採用できません")
    current = _required(candidate, "current_price_yen")
    if type(current) is not int or current <= 0:
        raise WeeklyPicksError("無料作品は初期対象外です。現在価格は正の整数（円）で入力してください")
    original = candidate.get("original_price_yen")
    discount = candidate.get("discount_percent")
    if kind == "sale":
        if type(original) is not int or type(discount) is not int:
            raise WeeklyPicksError("セール候補には通常価格と割引率が必要です")
        computed = calculated_discount(original, current)
        if discount != computed:
            raise WeeklyPicksError("割引率が通常価格と現在価格からの計算結果と一致しません")
        if discount < 20:
            raise WeeklyPicksError("20%未満のセールは対象外です")
    elif original is not None or discount is not None:
        raise WeeklyPicksError("新作候補のセール項目はnullにしてください")
    languages = _required(candidate, "japanese")
    if not isinstance(languages, dict) or set(languages) != LANGUAGE_KEYS:
        raise WeeklyPicksError("日本語対応はinterface・subtitles・full_audioを分けて入力してください")
    if any(value not in {True, False, None} for value in languages.values()):
        raise WeeklyPicksError("日本語対応はtrue・false・null（不明）のいずれかです")
    sources = _required(candidate, "sources")
    if not isinstance(sources, list) or not sources:
        raise WeeklyPicksError("出典がありません")
    normalized_sources: list[dict[str, str]] = []
    for source in sources:
        if not isinstance(source, dict) or set(source) != {"kind", "url"}:
            raise WeeklyPicksError("出典はkindとurlだけを持つ構造にしてください")
        source_kind = str(source["kind"])
        if source_kind not in {"primary", "auxiliary"}:
            raise WeeklyPicksError("出典種別が不正です")
        normalized_sources.append({"kind": source_kind, "url": normalize_url(str(source["url"]))})
    if not any(source["kind"] == "primary" for source in normalized_sources):
        raise WeeklyPicksError("公式一次情報がない候補は採用できません")
    status = str(candidate.get("release_status", "released"))
    if status not in {"released", "upcoming", "early_access"}:
        raise WeeklyPicksError("発売状態を安全に分類できません")
    flags = candidate.get("verification_flags", [])
    if not isinstance(flags, list) or any(flag not in {"source_conflict", "release_delayed", "price_changed"} for flag in flags):
        raise WeeklyPicksError("確認状態を安全に分類できません")
    if flags:
        raise WeeklyPicksError(f"公式情報の再確認が必要です: {flags[0]}")
    rank = candidate.get("editorial_rank", 0)
    if type(rank) is not int or not 0 <= rank <= 100:
        raise WeeklyPicksError("editorial_rankは0から100の整数です")
    verified_at = parse_verified_at(_required(candidate, "verified_at"))
    personal_comment = str(candidate.get("personal_comment", ""))
    editorial_reason = str(_required(candidate, "editorial_reason")).strip()
    if any(len(value) > 1000 for value in (personal_comment, editorial_reason)):
        raise WeeklyPicksError("私感または選定理由が長すぎます")
    assert_safe_text(personal_comment, "私感")
    assert_safe_text(editorial_reason, "選定理由")
    result = dict(candidate)
    result.update(
        steam_url=url,
        title=title,
        release_date=release_date.isoformat(),
        sources=normalized_sources,
        verified_at=verified_at.isoformat(timespec="seconds"),
        personal_comment=personal_comment,
        editorial_reason=editorial_reason,
        release_status=status,
        editorial_rank=rank,
    )
    return result


def validate_and_select(payload: dict[str, Any], history: Iterable[dict[str, Any]] = ()) -> tuple[WeekWindow, list[dict[str, Any]]]:
    week_id = str(_required(payload, "week_id"))
    if not SAFE_WEEK.fullmatch(week_id):
        raise WeeklyPicksError("week_idはYYYY-Www形式です")
    try:
        monday = date.fromisocalendar(int(week_id[:4]), int(week_id[-2:]), 1)
    except ValueError as exc:
        raise WeeklyPicksError("week_idが実在するISO週ではありません") from exc
    window = week_window(monday)
    if any(str(record.get("week_id")) == week_id and record.get("status") in {"generated", "published"} for record in history):
        raise WeeklyPicksError("同じ週の下書きまたは公開記録がすでにあります")
    raw_candidates = _required(payload, "candidates")
    if not isinstance(raw_candidates, list):
        raise WeeklyPicksError("candidatesは一覧形式にしてください")
    candidates = [validate_candidate(item, window) for item in raw_candidates]
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    historical_ids = {str(item) for record in history for item in record.get("app_ids", [])}
    for item in candidates:
        if item["app_id"] in seen_ids or item["app_id"] in historical_ids:
            raise WeeklyPicksError("同じ作品IDの重複を検出しました")
        if item["steam_url"] in seen_urls:
            raise WeeklyPicksError("正規化URLの重複を検出しました")
        seen_ids.add(item["app_id"])
        seen_urls.add(item["steam_url"])
    if len(candidates) < 5:
        raise WeeklyPicksError("条件を満たす候補が5本未満です。架空作品では補いません")
    releases = sorted((item for item in candidates if item["kind"] == "release"), key=_sort_key)
    sales = sorted((item for item in candidates if item["kind"] == "sale"), key=_sort_key)
    if not releases or not sales:
        raise WeeklyPicksError("新作とセールを最低1本ずつ含める必要があります")
    chosen = [releases[0], sales[0]]
    remainder = sorted((item for item in candidates if item not in chosen), key=_sort_key)
    chosen.extend(remainder[:3])
    return window, chosen


def _sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (-item["editorial_rank"], item["title"].casefold(), item["app_id"])


def facts_for_ai(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item[key]
        for key in (
            "app_id", "title", "steam_url", "kind", "release_date", "release_status",
            "region", "currency", "current_price_yen", "original_price_yen",
            "discount_percent", "japanese", "sources", "verified_at",
        )
    }


def facts_hash(item: dict[str, Any]) -> str:
    encoded = json.dumps(facts_for_ai(item), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_ai_request(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    return {
        "instruction": "公式事実を変更せず、未プレイ作品の短い紹介と選定理由だけを作る。体験、感想、人気、評価を捏造しない。",
        "items": [
            {"facts": facts_for_ai(item), "facts_sha256": facts_hash(item), "editorial_context": item["editorial_reason"]}
            for item in items
        ],
    }


def validate_ai_response(response: dict[str, Any], items: Iterable[dict[str, Any]]) -> dict[str, dict[str, str]]:
    expected = {item["app_id"]: item for item in items}
    rows = response.get("items")
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise WeeklyPicksError("AI応答の件数が選定結果と一致しません")
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != AI_ITEM_KEYS:
            raise WeeklyPicksError("AI応答に許可していないフィールドがあります")
        app_id = str(row["app_id"])
        if app_id not in expected or row["facts_sha256"] != facts_hash(expected[app_id]):
            raise WeeklyPicksError("AIが公式事実を変更した可能性があるため拒否しました")
        for key in ("official_summary", "editorial_reason"):
            if not isinstance(row[key], str) or len(row[key]) > 1000:
                raise WeeklyPicksError("AI文章を安全に解析できません")
            assert_safe_text(row[key], "AI文章")
        result[app_id] = {"official_summary": row["official_summary"], "editorial_reason": row["editorial_reason"]}
    return result


def _language_label(value: Any) -> str:
    return "対応" if value is True else "未対応" if value is False else "不明（要確認）"


def render_article(window: WeekWindow, items: list[dict[str, Any]], ai: dict[str, dict[str, str]] | None = None) -> str:
    slug = f"weekly-picks-{window.week_id.lower()}"
    lines = [
        "---", f'title: "{window.monday:%Y年%m月%d日}週 新作・セール5選"',
        f"date: {window.monday.isoformat()}", f"lastmod: {window.monday.isoformat()}", "draft: true",
        'description: "今週のPCゲーム新作とセールから、公式情報を確認した5本を紹介します。"',
        "images: []", "article_type: weekly_picks", 'spoiler_warning: ""', "provided: false",
        'author: "やまもと"', "corrections: []", f'week_id: "{window.week_id}"', "---", "",
        "> この記事は未プレイ作品の情報紹介であり、レビューやプレイ体験談ではありません。価格などは確認時点の情報です。", "",
    ]
    for number, item in enumerate(items, 1):
        generated = (ai or {}).get(item["app_id"], {})
        reason = generated.get("editorial_reason", item["editorial_reason"])
        lines.extend([
            f"## {number}. {item['title']}", "", f"- 種別: {'今週の新作' if item['kind'] == 'release' else 'セール'}",
            f"- 発売日: {item['release_date']}", f"- 価格: {item['current_price_yen']:,}円" + (f"（通常{item['original_price_yen']:,}円、{item['discount_percent']}%オフ）" if item['kind'] == 'sale' else ""),
            f"- 日本語: インターフェイス {_language_label(item['japanese']['interface'])}／字幕 {_language_label(item['japanese']['subtitles'])}／音声 {_language_label(item['japanese']['full_audio'])}",
            f"- [Steam公式ページ]({item['steam_url']})", f"- 公式情報確認: {item['verified_at']}", "",
            "### 公式情報に基づく概要", "", generated.get("official_summary", "下書き生成時点では手入力情報だけを使用しています。公式ページを参照してください。"), "",
            "### 選定理由", "", reason, "", "### やまもとの私感", "", item["personal_comment"] or "（私感は未入力です）", "",
        ])
    lines.extend(["---", "", f"記事識別子: `{slug}`", ""])
    return "\n".join(lines)


def render_social(window: WeekWindow, items: list[dict[str, Any]]) -> tuple[str, str]:
    names = "、".join(item["title"] for item in items)
    url = f"{{{{PUBLIC_URL}}}}/posts/weekly-picks-{window.week_id.lower()}/"
    morning = f"今週のPCゲーム新作・セール5選をまとめました。{names}。未プレイ作品の情報紹介です。\n{url}"
    evening = f"今週チェックしたいPCゲーム5本を、発売日・価格・日本語対応とともに紹介しています。価格は確認時点の情報です。\n{url}"
    return morning, evening


def notification_record(kind: str, window: WeekWindow, reason: str, count: int) -> dict[str, Any]:
    if kind not in {"attention", "error"}:
        raise WeeklyPicksError("通知分類が不正です")
    allowed = ATTENTION_REASONS if kind == "attention" else ERROR_REASONS
    if reason not in allowed:
        raise WeeklyPicksError("通知理由は固定分類だけを使用できます")
    return {"notification_type": kind, "week_id": window.week_id, "reason_code": reason, "candidate_count": count}


def atomic_write_tree(destination: Path, files: dict[str, str]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise WeeklyPicksError("同じ週の出力先がすでに存在します。自動上書きしません")
    temp = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    try:
        for relative, content in files.items():
            path = temp / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
        temp.rename(destination)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WeeklyPicksError("入力JSONを安全に読み取れません") from exc


def run(args: argparse.Namespace) -> int:
    payload = load_json(args.input)
    history = load_json(args.history) if args.history else []
    if not isinstance(payload, dict) or not isinstance(history, list):
        raise WeeklyPicksError("入力または履歴の形式が不正です")
    window, selected = validate_and_select(payload, history)
    ai_request = build_ai_request(selected)
    if args.print_ai_request:
        print(json.dumps(ai_request, ensure_ascii=False, indent=2))
    slug = f"weekly-picks-{window.week_id.lower()}"
    morning, evening = render_social(window, selected)
    evidence = {
        "week_id": window.week_id, "slug": slug, "status": "generated", "app_ids": [item["app_id"] for item in selected],
        "window": {"monday": window.monday.isoformat(), "sunday": window.sunday.isoformat(), "author_comment_deadline": sunday_deadline(window).isoformat()},
        "selected": [{**facts_for_ai(item), "personal_comment_present": bool(item["personal_comment"])} for item in selected],
        "external_requests": 0, "published": False, "discord_messages": 0, "social_posts": 0,
    }
    if args.dry_run:
        print(f"検証成功: {window.week_id} / 候補 {len(payload['candidates'])} 件 / 選定 5 件")
        print("外部通信・ファイル作成・公開: なし")
        return 0
    if not args.output:
        raise WeeklyPicksError("生成時は--outputが必要です")
    atomic_write_tree(args.output, {
        "index.md": render_article(window, selected),
        "weekly-picks-evidence.json": json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        "social/0730.txt": morning + "\n", "social/2000.txt": evening + "\n",
        "ai-request-dry-run.json": json.dumps(ai_request, ensure_ascii=False, indent=2) + "\n",
    })
    print(f"検証済み下書きを作成: {args.output}")
    print("draft: true / 外部通信・公開・SNS投稿・Discord通知: なし")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="手入力候補JSON")
    parser.add_argument("--history", type=Path, help="過去の生成・公開記録JSON（読み取り専用）")
    parser.add_argument("--output", type=Path, help="検証済み下書きの新規出力フォルダ")
    parser.add_argument("--dry-run", action="store_true", help="検証と選定だけを行い、ファイルを作らない")
    parser.add_argument("--print-ai-request", action="store_true", help="AIへ渡せる許可リストだけを表示")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        return run(build_parser().parse_args(argv))
    except WeeklyPicksError as exc:
        print(f"[要確認] {exc}", file=sys.stderr)
        return 1
    except Exception:
        print("[エラー] 下書き生成を安全に完了できませんでした。既存原稿は変更していません。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Apply five human-selected App IDs to a validated research result and build a draft."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import weekly_picks


class SelectionError(RuntimeError):
    pass


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SelectionError("選択資料を安全に読み取れません") from exc
    if not isinstance(value, dict):
        raise SelectionError("選択資料の形式が不正です")
    return value


def selected_payload(report: dict[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
    week_id = str(report.get("week_id", ""))
    if selection.get("week_id") != week_id:
        raise SelectionError("調査結果と選択結果の対象週が一致しません")
    ids = selection.get("selected_app_ids")
    if not isinstance(ids, list) or len(ids) != 5 or len(set(map(str, ids))) != 5:
        raise SelectionError("掲載候補は重複なしで5本選んでください")
    candidates = report.get("selected")
    if not isinstance(candidates, list):
        raise SelectionError("検証済み候補がありません")
    by_id = {str(item.get("app_id")): item for item in candidates if isinstance(item, dict)}
    if any(str(app_id) not in by_id for app_id in ids):
        raise SelectionError("候補一覧にない作品が選ばれています")
    chosen = [by_id[str(app_id)] for app_id in ids]
    if {item.get("kind") for item in chosen} != {"release", "sale"}:
        raise SelectionError("新作とセールを最低1本ずつ選んでください")
    return {"week_id": week_id, "candidates": chosen}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research-result", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--history", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = load_object(args.research_result)
        selection = load_object(args.selection)
        payload = selected_payload(report, selection)
        history = weekly_picks.load_json(args.history) if args.history else []
        window, selected = weekly_picks.validate_and_select(payload, history)
        weekly_args = SimpleNamespace(input=None, history=None, output=args.output, dry_run=False, print_ai_request=False)
        slug = f"weekly-picks-{window.week_id.lower()}"
        morning, evening = weekly_picks.render_social(window, selected)
        evidence = {
            "week_id": window.week_id, "slug": slug, "status": "generated",
            "app_ids": [item["app_id"] for item in selected],
            "window": {"monday": window.monday.isoformat(), "sunday": window.sunday.isoformat(), "author_comment_deadline": weekly_picks.sunday_deadline(window).isoformat()},
            "selected": [{**weekly_picks.facts_for_ai(item), "personal_comment_present": bool(item["personal_comment"])} for item in selected],
            "external_requests": 0, "published": False, "discord_messages": 0, "social_posts": 0,
        }
        weekly_picks.atomic_write_tree(args.output, {
            "index.md": weekly_picks.render_article(window, selected),
            "weekly-picks-evidence.json": json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
            "social/0730.txt": morning + "\n", "social/2000.txt": evening + "\n",
            "ai-request-dry-run.json": json.dumps(weekly_picks.build_ai_request(selected), ensure_ascii=False, indent=2) + "\n",
        })
        print(f"選択済み5本から検証済み下書きを作成: {args.output}")
        print("draft: true / 外部送信・公開: なし")
        return 0
    except (SelectionError, weekly_picks.WeeklyPicksError) as exc:
        print(f"[要確認] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

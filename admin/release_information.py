"""Phase Lの候補分類と日付表示を扱う副作用のない処理。"""

from __future__ import annotations

from datetime import datetime


def latest_cycle(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    cycle = max((str(row.get("cycle_key") or "") for row in rows), default="")
    return [row for row in rows if str(row.get("cycle_key") or "") == cycle]


def sections(rows: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    current = latest_cycle(rows)
    new = [row for row in current if row.get("status") == "active" and row.get("candidate_kind") == "new_release"][:5]
    sale = [row for row in current if row.get("status") == "active" and row.get("candidate_kind") in {"sale", "free"}][:5]
    selected = {str(row["id"]) for row in new + sale}
    other = [row for row in current if row.get("status") != "excluded" and str(row["id"]) not in selected]
    excluded = [row for row in current if row.get("status") == "excluded"]
    return {"new": new, "sale": sale, "other": other, "excluded": excluded}


def event_date(value: object) -> str | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        try:
            return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
        except ValueError:
            return None

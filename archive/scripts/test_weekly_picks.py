from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

import weekly_picks as weekly


def candidate(number: int, kind: str, *, release_date: str = "2026-08-10", rank: int = 50) -> dict:
    current = 800 if kind == "sale" else 2000
    return {
        "kind": kind,
        "app_id": str(100000 + number),
        "title": f"架空ゲーム{number}",
        "steam_url": f"https://store.steampowered.com/app/{100000 + number}/fictional-{number}/",
        "release_date": release_date,
        "release_status": "released" if kind == "sale" else "upcoming",
        "verification_flags": [],
        "region": "JP",
        "currency": "JPY",
        "current_price_yen": current,
        "original_price_yen": 1000 if kind == "sale" else None,
        "discount_percent": 20 if kind == "sale" else None,
        "japanese": {"interface": True, "subtitles": False, "full_audio": None},
        "sources": [{"kind": "primary", "url": f"https://store.steampowered.com/app/{100000 + number}/fictional-{number}/"}],
        "verified_at": "2026-08-09T20:00:00+09:00",
        "editorial_rank": rank,
        "editorial_reason": f"架空候補{number}の選定理由です。",
        "personal_comment": "" if number != 1 else "入力済みの私感",
    }


def payload() -> dict:
    return {"week_id": "2026-W33", "candidates": [candidate(1, "release", rank=90), candidate(2, "release", rank=70), candidate(3, "sale", release_date="2025-01-01", rank=80), candidate(4, "sale", release_date="2024-01-01", rank=60), candidate(5, "sale", release_date="2023-01-01", rank=50), candidate(6, "release", rank=40)]}


class WeekTests(unittest.TestCase):
    def test_week_crosses_month_and_year(self):
        window = weekly.week_window(date(2025, 12, 31))
        self.assertEqual((window.week_id, window.monday, window.sunday), ("2026-W01", date(2025, 12, 29), date(2026, 1, 4)))

    def test_datetime_is_converted_to_tokyo(self):
        window = weekly.week_window(datetime.fromisoformat("2026-08-09T16:00:00+00:00"))
        self.assertEqual(window.monday, date(2026, 8, 10))

    def test_sunday_24_is_next_monday_zero(self):
        deadline = weekly.sunday_deadline(weekly.week_window(date(2026, 8, 10)))
        self.assertEqual(deadline.isoformat(), "2026-08-17T00:00:00+09:00")


class ValidationTests(unittest.TestCase):
    def test_selects_exactly_five_with_both_kinds_deterministically(self):
        first = weekly.validate_and_select(payload())[1]
        second = weekly.validate_and_select(payload())[1]
        self.assertEqual([x["app_id"] for x in first], [x["app_id"] for x in second])
        self.assertEqual(len(first), 5)
        self.assertEqual({x["kind"] for x in first}, {"release", "sale"})

    def test_release_outside_week_is_rejected(self):
        data = payload(); data["candidates"][0]["release_date"] = "2026-08-17"
        with self.assertRaisesRegex(weekly.WeeklyPicksError, "対象週外"):
            weekly.validate_and_select(data)

    def test_under_twenty_percent_is_rejected(self):
        data = payload(); item = data["candidates"][2]; item.update(current_price_yen=810, discount_percent=19)
        with self.assertRaisesRegex(weekly.WeeklyPicksError, "20%未満"):
            weekly.validate_and_select(data)

    def test_discount_mismatch_is_rejected(self):
        data = payload(); data["candidates"][2]["discount_percent"] = 50
        with self.assertRaisesRegex(weekly.WeeklyPicksError, "一致しません"):
            weekly.validate_and_select(data)

    def test_non_jpy_and_unknown_region_are_rejected(self):
        for field, value in (("currency", "USD"), ("region", "")):
            data = payload(); data["candidates"][0][field] = value
            with self.assertRaisesRegex(weekly.WeeklyPicksError, "地域JP"):
                weekly.validate_and_select(data)

    def test_missing_original_price_is_rejected(self):
        data = payload(); data["candidates"][2]["original_price_yen"] = None
        with self.assertRaisesRegex(weekly.WeeklyPicksError, "通常価格"):
            weekly.validate_and_select(data)

    def test_free_game_is_excluded_initially(self):
        data = payload(); data["candidates"][0]["current_price_yen"] = 0
        with self.assertRaisesRegex(weekly.WeeklyPicksError, "無料作品"):
            weekly.validate_and_select(data)

    def test_language_categories_remain_separate(self):
        selected = weekly.validate_and_select(payload())[1]
        self.assertEqual(selected[0]["japanese"], {"interface": True, "subtitles": False, "full_audio": None})

    def test_missing_primary_source_is_rejected(self):
        data = payload(); data["candidates"][0]["sources"][0]["kind"] = "auxiliary"
        with self.assertRaisesRegex(weekly.WeeklyPicksError, "公式一次情報"):
            weekly.validate_and_select(data)

    def test_conflict_delay_and_price_change_require_attention(self):
        for flag in ("source_conflict", "release_delayed", "price_changed"):
            data = payload(); data["candidates"][0]["verification_flags"] = [flag]
            with self.assertRaisesRegex(weekly.WeeklyPicksError, flag):
                weekly.validate_and_select(data)

    def test_candidate_shortage_is_not_filled(self):
        data = payload(); data["candidates"] = data["candidates"][:4]
        with self.assertRaisesRegex(weekly.WeeklyPicksError, "5本未満"):
            weekly.validate_and_select(data)

    def test_duplicate_app_id_and_normalized_url_are_rejected(self):
        data = payload(); data["candidates"][1]["app_id"] = data["candidates"][0]["app_id"]; data["candidates"][1]["steam_url"] = data["candidates"][0]["steam_url"]
        with self.assertRaisesRegex(weekly.WeeklyPicksError, "作品ID"):
            weekly.validate_and_select(data)
        self.assertEqual(
            weekly.normalize_url("https://store.steampowered.com/app/100001/game/?x=1#part"),
            weekly.normalize_url("https://store.steampowered.com/app/100001/game"),
        )

    def test_history_blocks_week_and_previous_game(self):
        with self.assertRaisesRegex(weekly.WeeklyPicksError, "同じ週"):
            weekly.validate_and_select(payload(), [{"week_id": "2026-W33", "status": "generated", "app_ids": []}])
        with self.assertRaisesRegex(weekly.WeeklyPicksError, "作品ID"):
            weekly.validate_and_select(payload(), [{"week_id": "2026-W32", "status": "published", "app_ids": ["100001"]}])


class SafetyTests(unittest.TestCase):
    def test_draft_disclosure_and_empty_comment(self):
        window, selected = weekly.validate_and_select(payload())
        article = weekly.render_article(window, selected)
        self.assertIn("draft: true", article)
        self.assertNotIn("draft: false", article)
        self.assertIn("未プレイ作品", article)
        self.assertIn("レビューやプレイ体験談ではありません", article)
        self.assertIn("（私感は未入力です）", article)

    def test_personal_comment_is_not_sent_to_ai_or_changed(self):
        _, selected = weekly.validate_and_select(payload())
        request = weekly.build_ai_request(selected)
        serialized = json.dumps(request, ensure_ascii=False)
        self.assertNotIn("入力済みの私感", serialized)
        article = weekly.render_article(weekly.week_window(date(2026, 8, 10)), selected)
        self.assertIn("入力済みの私感", article)

    def test_ai_allowlist_excludes_pages_cookies_tokens_and_notes(self):
        _, selected = weekly.validate_and_select(payload())
        request = weekly.build_ai_request(selected)
        keys = set(request["items"][0]["facts"])
        self.assertNotIn("personal_comment", keys)
        self.assertTrue(keys.isdisjoint({"page_body", "cookie", "token", "other_article", "personal_notes"}))

    def test_secret_or_dangerous_text_is_rejected_without_echoing_value(self):
        data = payload(); data["candidates"][0]["personal_comment"] = "token=secret-value"
        with self.assertRaisesRegex(weekly.WeeklyPicksError, "値は表示しません") as raised:
            weekly.validate_and_select(data)
        self.assertNotIn("secret-value", str(raised.exception))

    def test_ai_fact_change_or_extra_fact_field_is_rejected(self):
        _, selected = weekly.validate_and_select(payload())
        rows = [{"app_id": item["app_id"], "facts_sha256": weekly.facts_hash(item), "official_summary": "概要", "editorial_reason": "理由"} for item in selected]
        weekly.validate_ai_response({"items": rows}, selected)
        changed = copy.deepcopy(rows); changed[0]["facts_sha256"] = "0" * 64
        with self.assertRaisesRegex(weekly.WeeklyPicksError, "公式事実"):
            weekly.validate_ai_response({"items": changed}, selected)
        extra = copy.deepcopy(rows); extra[0]["price"] = 1
        with self.assertRaisesRegex(weekly.WeeklyPicksError, "許可していない"):
            weekly.validate_ai_response({"items": extra}, selected)

    def test_sources_and_verified_time_are_traceable(self):
        window, selected = weekly.validate_and_select(payload())
        article = weekly.render_article(window, selected)
        self.assertIn(selected[0]["steam_url"], article)
        self.assertIn("2026-08-09T20:00:00+09:00", article)

    def test_atomic_generation_never_overwrites_and_leaves_no_partial(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name); destination = root / "draft"
            weekly.atomic_write_tree(destination, {"index.md": "complete", "social/0730.txt": "post"})
            self.assertEqual((destination / "index.md").read_text(), "complete")
            with self.assertRaisesRegex(weekly.WeeklyPicksError, "上書き"):
                weekly.atomic_write_tree(destination, {"index.md": "changed"})
            self.assertEqual((destination / "index.md").read_text(), "complete")
            self.assertFalse(any(root.glob(".draft-*")))

    def test_notification_has_fixed_minimal_fields(self):
        window = weekly.week_window(date(2026, 8, 10))
        record = weekly.notification_record("attention", window, "candidate_shortage", 4)
        self.assertEqual(set(record), {"notification_type", "week_id", "reason_code", "candidate_count"})
        with self.assertRaises(weekly.WeeklyPicksError):
            weekly.notification_record("attention", window, "free form secret", 4)

    def test_social_assets_are_local_placeholders(self):
        window, selected = weekly.validate_and_select(payload())
        morning, evening = weekly.render_social(window, selected)
        self.assertIn("{{PUBLIC_URL}}", morning)
        self.assertIn("{{PUBLIC_URL}}", evening)
        self.assertNotIn("token", morning.casefold())


if __name__ == "__main__":
    unittest.main()

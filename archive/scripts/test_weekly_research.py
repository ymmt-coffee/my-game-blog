from __future__ import annotations

import json
import os
import copy
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import weekly_research as research
from test_weekly_picks import payload


def result() -> dict:
    return {"candidates": payload()["candidates"], "search_queries_used": 6, "notes": ["模擬データ"]}


class FakeInteractions:
    def __init__(self): self.kwargs = None
    def create(self, **kwargs):
        self.kwargs = kwargs
        return type("Response", (), {"output_text": json.dumps(result(), ensure_ascii=False)})()


class FakeClient:
    def __init__(self, **kwargs): self.interactions = FakeInteractions(); self.closed = False
    def close(self): self.closed = True


class ResearchTests(unittest.TestCase):
    def test_missing_key_stops_before_client(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(research.ResearchError, "GEMINI_API_KEY"):
            research.call_gemini("2026-W33", lambda **_: self.fail("called"))

    def test_gemini_uses_search_url_context_schema_and_no_storage(self):
        made = []
        def factory(**kwargs):
            client = FakeClient(); made.append((kwargs, client)); return client
        with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-test-key"}, clear=True):
            response = research.call_gemini("2026-W33", factory)
        kwargs, client = made[0]
        self.assertEqual(kwargs, {"api_key": "fake-test-key"})
        self.assertEqual(client.interactions.kwargs["tools"], [{"type": "google_search"}, {"type": "url_context"}])
        self.assertFalse(client.interactions.kwargs["store"])
        self.assertEqual(response["search_queries_used"], 6)
        self.assertTrue(client.closed)

    def test_limits_are_enforced(self):
        data = result(); data["search_queries_used"] = 21
        class TooMany(FakeClient):
            def __init__(self, **kwargs):
                super().__init__(); self.interactions.create = lambda **_: type("R", (), {"output_text": json.dumps(data)})()
        with patch.dict(os.environ, {"GEMINI_API_KEY": "fake"}, clear=True), self.assertRaisesRegex(research.ResearchError, "検索回数"):
            research.call_gemini("2026-W33", TooMany)

    def test_api_steps_override_model_reported_query_count(self):
        data = result(); data["search_queries_used"] = 999
        class WithSteps(FakeClient):
            def __init__(self, **kwargs):
                super().__init__()
                steps = [type("Step", (), {"type": "google_search_call"})() for _ in range(3)]
                self.interactions.create = lambda **_: type("R", (), {"output_text": json.dumps(data), "steps": steps})()
        with patch.dict(os.environ, {"GEMINI_API_KEY": "fake"}, clear=True):
            self.assertEqual(research.call_gemini("2026-W33", WithSteps)["search_queries_used"], 3)

    def test_existing_validator_selects_five(self):
        report, selected = research.validate_result("2026-W33", result())
        self.assertEqual(len(selected), 6)
        self.assertEqual(report["candidate_count"], 6)

    def test_shortlist_contains_up_to_five_of_each_kind(self):
        data = result()
        for number, source_index in ((7, 0), (8, 1), (9, 2), (10, 3)):
            item = copy.deepcopy(data["candidates"][source_index])
            item["app_id"] = str(100000 + number)
            item["title"] = f"架空ゲーム{number}"
            item["steam_url"] = f"https://store.steampowered.com/app/{100000 + number}/fictional-{number}/"
            item["sources"] = [{"kind": "primary", "url": item["steam_url"]}]
            data["candidates"].append(item)
        report, shortlist = research.validate_result("2026-W33", data)
        self.assertEqual((len(report["release_candidates"]), len(report["sale_candidates"])), (5, 5))
        self.assertEqual(len(shortlist), 10)

    def test_release_sale_only_fields_are_removed_before_validation(self):
        data = result()
        data["candidates"][0]["original_price_yen"] = 3000
        data["candidates"][0]["discount_percent"] = 33
        report, _ = research.validate_result("2026-W33", data)
        release = next(item for item in report["selected"] if item["app_id"] == "100001")
        self.assertIsNone(release["original_price_yen"])
        self.assertIsNone(release["discount_percent"])

    def test_program_derives_ids_discount_region_and_timestamp(self):
        data = result()
        item = data["candidates"][2]
        item.update(app_id="wrong", kind="release", current_price_yen="¥800", original_price_yen="1,000円", discount_percent=99, region="US", currency="USD", verified_at="no timezone")
        fixed = research.canonicalize_result("2026-W33", data, datetime.fromisoformat("2026-08-09T21:30:00+09:00"))
        sale = next(candidate for candidate in fixed["candidates"] if candidate["steam_url"].endswith("fictional-3"))
        self.assertEqual((sale["app_id"], sale["kind"], sale["discount_percent"]), ("100003", "sale", 20))
        self.assertEqual((sale["region"], sale["currency"], sale["verified_at"]), ("JP", "JPY", "2026-08-09T21:30:00+09:00"))

    def test_incomplete_candidates_are_excluded_before_strict_validation(self):
        data = result(); data["candidates"].append({"title": "不完全"})
        fixed = research.canonicalize_result("2026-W33", data)
        self.assertEqual(len(fixed["candidates"]), 6)
        self.assertIn("1件除外", fixed["notes"][-1])

    def test_html_escapes_text_and_has_no_script(self):
        data = result(); data["candidates"][0]["editorial_reason"] = "A < B & C"
        report, _ = research.validate_result("2026-W33", data)
        page = research.render_html(report)
        self.assertNotIn("<script>", page)
        self.assertIn("A &lt; B &amp; C", page)
        self.assertIn("Content-Security-Policy", page)

    def test_dangerous_html_is_rejected_before_rendering(self):
        data = result(); data["candidates"][0]["editorial_reason"] = "<script>alert(1)</script>"
        with self.assertRaisesRegex(Exception, "危険な文字列"):
            research.validate_result("2026-W33", data)

    def test_discord_is_minimal_and_mentions_disabled(self):
        report, _ = research.validate_result("2026-W33", result())
        body = research.discord_payload(report)
        self.assertEqual(body["allowed_mentions"]["parse"], [])
        self.assertNotIn("架空ゲーム", body["content"])
        self.assertNotIn("http", body["content"])

    def test_all_outputs_are_created(self):
        report, _ = research.validate_result("2026-W33", result())
        with tempfile.TemporaryDirectory() as folder:
            paths = research.write_outputs(report, Path(folder))
            self.assertTrue(all(path.exists() for path in paths))
            self.assertEqual(paths[1].read_bytes()[:4], b"%PDF")
            selection = json.loads(paths[3].read_text(encoding="utf-8"))
            self.assertEqual(selection["choose_exactly"], 5)
            self.assertEqual(selection["selected_app_ids"], [])
            saved = json.loads(paths[4].read_text(encoding="utf-8"))
            self.assertEqual(saved["week_id"], "2026-W33")
            self.assertEqual(len(saved["selected"]), 6)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import apply_weekly_selection as apply_selection
import weekly_research
from test_weekly_research import result


class ApplySelectionTests(unittest.TestCase):
    def setUp(self):
        self.report, _ = weekly_research.validate_result("2026-W33", result())
        choices = [{"app_id": item["app_id"], "title": item["title"], "kind": item["kind"]} for item in self.report["selected"]]
        ids = ["100001", "100002", "100003", "100004", "100005"]
        self.selection = {"week_id": "2026-W33", "choose_exactly": 5, "selected_app_ids": ids, "choices": choices}

    def test_builds_exact_selected_payload(self):
        payload = apply_selection.selected_payload(self.report, self.selection)
        self.assertEqual([item["app_id"] for item in payload["candidates"]], self.selection["selected_app_ids"])

    def test_requires_exactly_five_unique_candidates(self):
        for ids in (["100001"] * 5, ["100001", "100002"]):
            selection = dict(self.selection, selected_app_ids=ids)
            with self.assertRaisesRegex(apply_selection.SelectionError, "5本"):
                apply_selection.selected_payload(self.report, selection)

    def test_rejects_unknown_and_week_mismatch(self):
        with self.assertRaisesRegex(apply_selection.SelectionError, "候補一覧にない"):
            apply_selection.selected_payload(self.report, dict(self.selection, selected_app_ids=["x", "100002", "100003", "100004", "100005"]))
        with self.assertRaisesRegex(apply_selection.SelectionError, "対象週"):
            apply_selection.selected_payload(self.report, dict(self.selection, week_id="2026-W34"))

    def test_requires_release_and_sale(self):
        only_releases = [item for item in self.report["selected"] if item["kind"] == "release"]
        self.report["selected"] = only_releases * 2
        selection = dict(self.selection, selected_app_ids=[only_releases[0]["app_id"], only_releases[1]["app_id"], only_releases[2]["app_id"], "x", "y"])
        with self.assertRaises(apply_selection.SelectionError):
            apply_selection.selected_payload(self.report, selection)


if __name__ == "__main__":
    unittest.main()

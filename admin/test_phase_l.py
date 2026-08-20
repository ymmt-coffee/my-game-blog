from __future__ import annotations

import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from admin import db, game_information, release_information
from admin.app import create_app


class PhaseLReleaseInformationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "state" / "admin.sqlite3"
        self.content = self.root / "content" / "articles"
        self.app = create_app(db_path=self.db_path, content_root=self.content, state_root=self.root / "state", legacy_root=self.root / "legacy", testing=True)
        self.context = TestClient(self.app)
        self.client = self.context.__enter__()
        self.csrf = self.app.state.csrf_token

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)
        self.temporary.cleanup()

    def add_candidate(self, app_id: str, title: str, kind: str, status: str = "active", score: int = 80) -> tuple[dict[str, object], dict[str, object]]:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        game = game_information.GameRecord(
            steam_app_id=app_id, title=title,
            store_url=f"https://store.steampowered.com/app/{app_id}/?cc=jp&l=japanese",
            release_date="2026-09-10", japan_availability="available",
            japanese_support="confirmed", single_player="yes", verified_at=now,
        ).validated()
        price = game_information.PriceRecord(
            currency="JPY", regular_price=5000, current_price=3000, discount_percent=40,
            sale_ends_at="2026-08-30T15:00:00+00:00", source_url=str(game["store_url"]), observed_at=now,
        ).validated()
        db.save_game_observation(game, price=price, db_path=self.db_path)
        candidate = game_information.CandidateRecord(
            id=uuid.uuid4().hex, steam_app_id=app_id, cycle_key="2026-W34",
            candidate_kind=kind, status=status, interest_score=30, momentum_score=20,
            review_score=10, price_score=10, diversity_score=10,
            reasons=("Phase Lテスト",), exclusion_reason="テスト除外" if status == "excluded" else None,
        ).validated()
        db.save_game_candidate(candidate, self.db_path)
        return game, price

    def test_sections_use_latest_cycle_and_limits(self) -> None:
        rows = [
            {"id": "1", "cycle_key": "2026-W34", "candidate_kind": "new_release", "status": "active"},
            {"id": "2", "cycle_key": "2026-W34", "candidate_kind": "sale", "status": "active"},
            {"id": "3", "cycle_key": "2026-W34", "candidate_kind": "manual", "status": "unconfirmed"},
            {"id": "4", "cycle_key": "2026-W34", "candidate_kind": "sale", "status": "excluded"},
            {"id": "5", "cycle_key": "2026-W33", "candidate_kind": "new_release", "status": "active"},
        ]
        grouped = release_information.sections(rows)
        self.assertEqual([row["id"] for row in grouped["new"]], ["1"])
        self.assertEqual([row["id"] for row in grouped["sale"]], ["2"])
        self.assertEqual([row["id"] for row in grouped["other"]], ["3"])
        self.assertEqual([row["id"] for row in grouped["excluded"]], ["4"])

    def test_page_groups_candidates(self) -> None:
        self.add_candidate("1001", "新作候補", "new_release")
        self.add_candidate("1002", "セール候補", "sale")
        self.add_candidate("1003", "除外候補", "sale", "excluded")
        response = self.client.get("/collection")
        self.assertEqual(response.status_code, 200)
        for label in ("新作候補 5本", "セール・無料候補 5本", "その他候補", "除外候補"):
            self.assertIn(label, response.text)

        selection_page = self.client.get("/releases")
        self.assertEqual(selection_page.status_code, 200)
        self.assertIn("今週の記事候補", selection_page.text)
        self.assertIn("掲載候補に追加", selection_page.text)
        self.assertNotIn("最大10件で候補試運転", selection_page.text)

    def test_each_weekly_selection_kind_is_limited_to_five(self) -> None:
        for number in range(1, 7):
            app_id = f"11{number:02d}"
            self.add_candidate(app_id, f"新作{number}", "new_release")
            response = self.client.post(
                "/releases/select",
                data={
                    "csrf_token": self.csrf, "cycle_key": "2026-W34",
                    "steam_app_id": app_id, "selection_kind": "new_release", "selected": "1",
                },
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303 if number <= 5 else 400)
        self.assertEqual(len(db.list_weekly_release_selections("2026-W34", self.db_path)), 5)

    def test_refresh_and_draft_recheck_official_data(self) -> None:
        game, price = self.add_candidate("2001", "再確認候補", "sale")
        with patch("admin.app.game_collection.fetch_steam_game", return_value=(game, price)) as fetch:
            refreshed = self.client.post("/collection/candidates/2001/refresh", data={"csrf_token": self.csrf}, follow_redirects=False)
            selected = self.client.post("/releases/select", data={"csrf_token": self.csrf, "cycle_key": "2026-W34", "steam_app_id": "2001", "selection_kind": "sale", "selected": "1"}, follow_redirects=False)
            drafted = self.client.post("/releases/draft", data={"csrf_token": self.csrf, "cycle_key": "2026-W34"}, follow_redirects=False)
        self.assertEqual(refreshed.status_code, 303)
        self.assertEqual(drafted.status_code, 303)
        self.assertEqual(selected.status_code, 303)
        self.assertEqual(fetch.call_count, 2)
        self.assertTrue(any(self.content.glob("*/index.md")))
        self.assertIn("draft: true", next(self.content.glob("*/index.md")).read_text(encoding="utf-8"))

    def test_selected_dates_appear_in_calendar_and_can_be_removed(self) -> None:
        self.add_candidate("3001", "予定候補", "new_release")
        added = self.client.post("/collection/candidates/3001/calendar", data={"csrf_token": self.csrf, "event_kind": "release", "selected": "1"}, follow_redirects=False)
        self.assertEqual(added.status_code, 303)
        calendar = self.client.get("/schedule?view=month&date_value=2026-09-10")
        self.assertIn("予定候補", calendar.text)
        self.assertIn("発売日", calendar.text)
        removed = self.client.post("/collection/candidates/3001/calendar", data={"csrf_token": self.csrf, "event_kind": "release", "selected": "0"}, follow_redirects=False)
        self.assertEqual(removed.status_code, 303)
        self.assertEqual(db.list_game_calendar_events(self.db_path), [])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sqlite3
import tempfile
import unittest
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from admin import db, editorial, game_information
from admin.app import create_app


class PhaseKEditorialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "state" / "admin.sqlite3"
        self.content_root = self.root / "content" / "articles"
        self.app = create_app(
            db_path=self.db_path, content_root=self.content_root,
            state_root=self.root / "state", legacy_root=self.root / "legacy", testing=True,
        )
        self.context = TestClient(self.app)
        self.client = self.context.__enter__()
        self.csrf = self.app.state.csrf_token

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)
        self.temporary.cleanup()

    def add_candidate(self, app_id: str, title: str, kind: str, score: int) -> None:
        game = game_information.GameRecord(
            steam_app_id=app_id, title=title,
            store_url=f"https://store.steampowered.com/app/{app_id}/",
            japan_availability="available", japanese_support="confirmed",
            single_player="yes", review_percent=85, review_count=100,
        ).validated()
        db.save_game_observation(game, db_path=self.db_path)
        candidate = game_information.CandidateRecord(
            id=uuid.uuid4().hex, steam_app_id=app_id, cycle_key="2026-W34",
            candidate_kind=kind, status="active",
            interest_score=min(score, 35), momentum_score=min(max(score - 35, 0), 25),
            review_score=min(max(score - 60, 0), 15),
            price_score=min(max(score - 75, 0), 15),
            diversity_score=min(max(score - 90, 0), 10), reasons=("テスト候補",),
        ).validated()
        db.save_game_candidate(candidate, self.db_path)

    def test_top_three_mix_release_sale_and_highest_remaining(self) -> None:
        rows = [
            {"title": "総合", "status": "active", "cycle_key": "2026-W34", "candidate_kind": "editorial", "total_score": 99},
            {"title": "新作", "status": "active", "cycle_key": "2026-W34", "candidate_kind": "new_release", "total_score": 70},
            {"title": "セール", "status": "active", "cycle_key": "2026-W34", "candidate_kind": "sale", "total_score": 65},
            {"title": "旧周期", "status": "active", "cycle_key": "2026-W33", "candidate_kind": "new_release", "total_score": 100},
        ]
        selected = editorial.select_top_candidates(rows)
        self.assertEqual({row["title"] for row in selected}, {"総合", "新作", "セール"})

    def test_recent_decisions_are_not_immediately_recommended_again(self) -> None:
        now = datetime.now(timezone.utc)
        rows = [
            {"title": "保留中", "status": "active", "cycle_key": "2026-W34", "candidate_kind": "new_release", "total_score": 90, "latest_decision": "hold", "latest_decision_at": now.isoformat()},
            {"title": "再提案可", "status": "active", "cycle_key": "2026-W34", "candidate_kind": "new_release", "total_score": 80, "latest_decision": "hold", "latest_decision_at": (now - timedelta(days=15)).isoformat()},
            {"title": "興味なし", "status": "active", "cycle_key": "2026-W34", "candidate_kind": "sale", "total_score": 95, "latest_decision": "not_interested", "latest_decision_at": (now - timedelta(days=100)).isoformat()},
        ]
        selected = editorial.select_top_candidates(rows)
        self.assertEqual([row["title"] for row in selected], ["再提案可"])

    def test_budget_requires_exception_and_stops_above_twenty_thousand(self) -> None:
        with self.assertRaises(editorial.EditorialError):
            editorial.validate_purchase("3000", False, "", 9000)
        self.assertEqual(editorial.validate_purchase("3000", True, "", 9000)[0], 3000)
        with self.assertRaises(editorial.EditorialError):
            editorial.validate_purchase("9000", True, "", 12000)

    def test_page_records_decision_purchase_and_play_review(self) -> None:
        self.add_candidate("111", "新作ゲーム", "new_release", 75)
        self.add_candidate("222", "セールゲーム", "sale", 70)
        response = self.client.get("/editorial")
        self.assertEqual(response.status_code, 200)
        self.assertIn("今週の候補", response.text)
        self.assertIn("新作ゲーム", response.text)
        decision = self.client.post(
            "/editorial/candidates/111/decision",
            data={"csrf_token": self.csrf, "decision": "play_candidate", "note": "遊ぶ"},
            follow_redirects=False,
        )
        self.assertEqual(decision.status_code, 303)
        purchase = self.client.post(
            "/editorial/candidates/111/purchase",
            data={"csrf_token": self.csrf, "purchased_on": "2026-08-19", "price_jpy": "5000"},
            follow_redirects=False,
        )
        self.assertEqual(purchase.status_code, 303)
        review = self.client.post(
            "/editorial/candidates/111/play-review",
            data={"csrf_token": self.csrf, "play_status": "playing", "rating": "good", "note": "良い"},
            follow_redirects=False,
        )
        self.assertEqual(review.status_code, 303)
        activity = db.editorial_activity("2026-08", self.db_path)
        self.assertEqual(activity["purchase_total"], 5000)
        self.assertEqual(activity["play_reviews"][0]["rating"], "good")

    def test_explicit_draft_creation_creates_incomplete_unpublished_article(self) -> None:
        self.add_candidate("333", "記事候補ゲーム", "new_release", 80)
        response = self.client.post(
            "/editorial/candidates/333/draft",
            data={"csrf_token": self.csrf, "article_type": "play_note"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].startswith("/articles/"))
        with closing(sqlite3.connect(self.db_path)) as connection:
            article = connection.execute("SELECT state,article_type FROM articles").fetchone()
            link = connection.execute("SELECT steam_app_id,article_type FROM game_article_drafts").fetchone()
        self.assertEqual(article, ("draft", "play_note"))
        self.assertEqual(link, ("333", "play_note"))
        index = next(self.content_root.glob("*/index.md")).read_text(encoding="utf-8")
        self.assertIn("draft: true", index)
        self.assertIn("description: ''", index)

    def test_editorial_records_can_be_removed_without_deleting_article(self) -> None:
        self.add_candidate("555", "削除確認ゲーム", "new_release", 80)
        self.client.post("/editorial/candidates/555/decision", data={"csrf_token": self.csrf, "decision": "hold"})
        self.client.post("/editorial/candidates/555/purchase", data={"csrf_token": self.csrf, "purchased_on": "2026-08-19", "price_jpy": "1000"})
        self.client.post("/editorial/candidates/555/play-review", data={"csrf_token": self.csrf, "play_status": "playing", "rating": "unrated"})
        self.client.post("/editorial/candidates/555/draft", data={"csrf_token": self.csrf, "article_type": "play_note"}, follow_redirects=False)
        activity = db.editorial_activity("2026-08", self.db_path)

        routes = [
            (f'/editorial/decisions/{activity["decisions"][0]["id"]}/delete', "decisions"),
            (f'/editorial/purchases/{activity["purchases"][0]["id"]}/delete', "purchases"),
            (f'/editorial/play-reviews/{activity["play_reviews"][0]["id"]}/delete', "play_reviews"),
            (f'/editorial/drafts/{activity["drafts"][0]["id"]}/unlink', "drafts"),
        ]
        for route, _ in routes:
            response = self.client.post(route, data={"csrf_token": self.csrf}, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
        emptied = db.editorial_activity("2026-08", self.db_path)
        for _, key in routes:
            self.assertEqual(emptied[key], [])
        self.assertTrue(any(self.content_root.glob("*/index.md")))

    def test_no_article_option_does_not_create_a_file(self) -> None:
        self.add_candidate("444", "プレイ専用", "new_release", 60)
        response = self.client.post(
            "/editorial/candidates/444/draft",
            data={"csrf_token": self.csrf, "article_type": "no_article"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(any(self.content_root.glob("*/index.md")))


if __name__ == "__main__":
    unittest.main()

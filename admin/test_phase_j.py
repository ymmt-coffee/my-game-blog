from __future__ import annotations

import sqlite3
import tempfile
import unittest
import uuid
import os
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from admin import db, game_collection, game_information
from admin.app import create_app


class PhaseJSharedGameInformationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "state" / "admin.sqlite3"
        self.app = create_app(
            db_path=self.db_path, content_root=self.root / "content" / "articles",
            state_root=self.root / "state", legacy_root=self.root / "legacy", testing=True,
        )
        self.context = TestClient(self.app)
        self.client = self.context.__enter__()

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)
        self.temporary.cleanup()

    def game(self) -> dict[str, object]:
        return game_information.GameRecord(
            steam_app_id="123456", title="テストゲーム",
            store_url="https://store.steampowered.com/app/123456/",
            japan_availability="available", japanese_support="confirmed",
            single_player="yes", review_percent=88, review_count=120,
            wishlisted=True,
        ).validated()

    def test_schema_contains_phase_j_tables_without_secret_columns(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as connection:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            columns = {row[1] for row in connection.execute("PRAGMA table_info(games)")}
        self.assertTrue({"games", "game_sources", "game_prices", "game_candidates",
                         "game_decisions", "game_collection_runs"}.issubset(tables))
        self.assertFalse({"api_key", "token", "cookie", "steam_id"} & columns)

    def test_observation_is_upserted_with_source_and_price_history(self) -> None:
        observed = datetime.now(timezone.utc).isoformat(timespec="seconds")
        source = game_information.SourceRecord(
            source_kind="rss", source_name="AUTOMATON",
            url="https://example.com/news/1", article_title="紹介記事",
            summary="短い要約", candidate_reason="新作として紹介",
        ).validated()
        price = game_information.PriceRecord(
            currency="JPY", regular_price=3000, current_price=2400,
            discount_percent=20, source_url="https://store.steampowered.com/app/123456/",
            observed_at=observed,
        ).validated()
        db.save_game_observation(self.game(), source, price, self.db_path)
        db.save_game_observation(self.game(), source, price, self.db_path)
        summary = db.game_information_summary(self.db_path)
        self.assertEqual((summary["games"], summary["sources"], summary["prices"]), (1, 1, 1))

    def test_candidate_scores_are_calculated_and_listed(self) -> None:
        db.save_game_observation(self.game(), db_path=self.db_path)
        candidate = game_information.CandidateRecord(
            id=uuid.uuid4().hex, steam_app_id="123456", cycle_key="2026-W33",
            candidate_kind="new_release", status="active", interest_score=30,
            momentum_score=20, review_score=10, price_score=8, diversity_score=7,
            reasons=("ウィッシュリスト登録済み", "新作"),
        ).validated()
        db.save_game_candidate(candidate, self.db_path)
        item = db.list_game_candidates(self.db_path)[0]
        self.assertEqual(item["total_score"], 75)
        self.assertEqual(item["title"], "テストゲーム")

    def test_non_steam_refresh_does_not_erase_owned_or_wishlist_state(self) -> None:
        synced = self.game()
        synced["owned"], synced["steam_synced_at"] = True, datetime.now(timezone.utc).isoformat()
        db.save_game_observation(synced, db_path=self.db_path)
        refresh = self.game()
        refresh["owned"], refresh["wishlisted"], refresh["steam_synced_at"] = None, None, None
        db.save_game_observation(refresh, db_path=self.db_path)
        with closing(sqlite3.connect(self.db_path)) as connection:
            values = connection.execute(
                "SELECT owned,wishlisted FROM games WHERE steam_app_id='123456'"
            ).fetchone()
        self.assertEqual(values, (1, 1))

    def test_decision_and_collection_run_are_preserved(self) -> None:
        db.save_game_observation(self.game(), db_path=self.db_path)
        db.record_game_decision("123456", "hold", "次のセールを待つ", self.db_path)
        db.start_game_collection_run("trial-1", "trial", 10, self.db_path)
        db.finish_game_collection_run(
            "trial-1", "success", "試運転を完了しました。",
            items_discovered=10, items_stored=1, apify_items=1, apify_cost_usd=0.01,
            db_path=self.db_path,
        )
        summary = db.game_information_summary(self.db_path)
        self.assertEqual(summary["last_run"]["status"], "success")
        with closing(sqlite3.connect(self.db_path)) as connection:
            decision = connection.execute("SELECT decision,note FROM game_decisions").fetchone()
        self.assertEqual(decision, ("hold", "次のセールを待つ"))

    def test_invalid_candidate_decision_is_rejected(self) -> None:
        db.save_game_observation(self.game(), db_path=self.db_path)
        with self.assertRaises(ValueError):
            db.record_game_decision("123456", "purchase_now", db_path=self.db_path)

    def test_invalid_external_values_are_rejected_before_storage(self) -> None:
        with self.assertRaises(game_information.GameInformationError):
            game_information.GameRecord(
                steam_app_id="123; rm", title="不正", store_url="javascript:alert(1)"
            ).validated()
        with self.assertRaises(game_information.GameInformationError):
            game_information.PriceRecord(
                currency="USD", source_url="https://example.com", observed_at="bad"
            ).validated()
        with self.assertRaises(game_information.GameInformationError):
            game_information.SourceRecord(
                source_kind="rss", source_name="媒体", url="https://example.com",
                published_at="not-a-date",
            ).validated()

    def test_release_page_shows_foundation_without_external_collection(self) -> None:
        response = self.client.get("/releases")
        self.assertEqual(response.status_code, 200)
        self.assertIn("収集準備", response.text)
        self.assertIn("試運転前のため候補はありません", response.text)
        self.assertIn("Apify APIトークン", response.text)
        self.assertIn("APIトークン設定後に接続確認", response.text)

    def test_apify_api_trial_stores_three_observations_without_exposing_token(self) -> None:
        observations = []
        for app_id, title in (("620", "Portal 2"), ("413150", "Stardew Valley"), ("1245620", "ELDEN RING")):
            game = game_information.GameRecord(
                steam_app_id=app_id, title=title,
                store_url=f"https://store.steampowered.com/app/{app_id}/",
                japan_availability="available", japanese_support="unknown", single_player="yes",
                verified_at="2026-08-15T04:05:37+00:00",
            ).validated()
            price = game_information.PriceRecord(
                currency="JPY", regular_price=1000, current_price=1000, discount_percent=0,
                source_url=str(game["store_url"]), observed_at="2026-08-15T04:05:37+00:00",
            ).validated()
            observations.append((game, price))
        with patch.dict(os.environ, {"APIFY_API_TOKEN": "private-token"}), patch(
            "admin.game_collection.run_apify_trial", return_value=observations
        ) as runner:
            response = self.client.post(
                "/releases/apify-trial", data={"csrf_token": self.app.state.csrf_token},
                follow_redirects=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("3件接続確認が完了", response.text)
        self.assertNotIn("private-token", response.text)
        runner.assert_called_once_with("private-token")
        summary = db.game_information_summary(self.db_path)
        self.assertEqual((summary["games"], summary["prices"]), (3, 3))
        self.assertEqual(summary["last_run"]["status"], "success")

    def test_apify_trial_requires_token(self) -> None:
        with patch("admin.game_collection.apify_api_token", return_value=""):
            response = self.client.post(
                "/releases/apify-trial", data={"csrf_token": self.app.state.csrf_token}
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Apify APIトークン", response.text)

    def test_candidate_trial_stores_scored_candidates_after_explicit_button(self) -> None:
        items = []
        for index in range(10):
            app_id = str(900000 + index)
            game = game_information.GameRecord(
                steam_app_id=app_id, title=f"候補{index + 1}",
                store_url=f"https://store.steampowered.com/app/{app_id}/",
                japan_availability="available", japanese_support="confirmed", single_player="yes",
                verified_at="2026-08-15T04:05:37+00:00",
            ).validated()
            candidate = game_information.CandidateRecord(
                id=f"2026-W33-{app_id}-new_release", steam_app_id=app_id,
                cycle_key="2026-W33", candidate_kind="new_release", status="active",
                interest_score=0, momentum_score=15, review_score=0,
                price_score=5, diversity_score=10, reasons=("Steam新作一覧から発見",),
            ).validated()
            items.append(game_collection.CandidateTrialItem(game, None, candidate))
        with patch("admin.game_collection.apify_api_token", return_value="private-token"), patch(
            "admin.game_collection.run_candidate_trial",
            return_value=game_collection.CandidateTrialResult(tuple(items), 10),
        ) as runner:
            response = self.client.post(
                "/releases/candidate-trial", data={"csrf_token": self.app.state.csrf_token},
                follow_redirects=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("最大10件の候補試運転が完了", response.text)
        self.assertNotIn("private-token", response.text)
        self.assertEqual(len(db.list_game_candidates(self.db_path)), 10)
        runner.assert_called_once_with("private-token")

        decision_response = self.client.post(
            "/releases/candidates/900000/decision",
            data={"csrf_token": self.app.state.csrf_token, "decision": "play_candidate"},
            follow_redirects=True,
        )
        self.assertEqual(decision_response.status_code, 200)
        self.assertIn("プレイ候補", decision_response.text)
        self.assertEqual(db.list_game_candidates(self.db_path)[0]["latest_decision"], "play_candidate")


if __name__ == "__main__":
    unittest.main()

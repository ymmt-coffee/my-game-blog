from __future__ import annotations

import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from admin import db, game_collection, game_information, game_scheduling


class GameSchedulingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temporary.name) / "admin.sqlite3"
        db.initialize(self.db_path)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def result(self) -> game_collection.CandidateTrialResult:
        game = game_information.GameRecord(
            steam_app_id="123456", title="テストゲーム",
            store_url="https://store.steampowered.com/app/123456/",
            japan_availability="available", japanese_support="confirmed", single_player="yes",
        ).validated()
        candidate = game_information.CandidateRecord(
            id="2026-W33-123456-new_release", steam_app_id="123456", cycle_key="2026-W33",
            candidate_kind="new_release", status="active", interest_score=0,
            momentum_score=15, review_score=0, price_score=5, diversity_score=10,
        ).validated()
        return game_collection.CandidateTrialResult((
            game_collection.CandidateTrialItem(game, None, candidate),
        ), 1)

    def test_thursday_run_is_caught_up_once(self) -> None:
        now = datetime(2026, 8, 15, 0, 0, tzinfo=timezone.utc)
        calls = []

        def collector(token: str, **kwargs):
            calls.append((token, kwargs))
            return self.result()

        with patch("admin.game_scheduling.game_collection._environment_secret", return_value=""):
            first = game_scheduling.process_due_weekly_collection(
                self.db_path, now=now, token="test-token", collector=collector,
            )
            second = game_scheduling.process_due_weekly_collection(
                self.db_path, now=now, token="test-token", collector=collector,
            )
        self.assertEqual((first, second), ("partial", "already_processed"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(db.game_information_summary(self.db_path)["games"], 1)

    def test_missing_token_does_not_create_failed_run(self) -> None:
        result = game_scheduling.process_due_weekly_collection(
            self.db_path, now=datetime(2026, 8, 15, tzinfo=timezone.utc), token="",
        )
        self.assertEqual(result, "credentials_missing")
        self.assertIsNone(db.game_information_summary(self.db_path)["last_run"])

    def test_owned_snapshot_is_atomic_and_preserves_wishlist(self) -> None:
        first = game_information.GameRecord(
            steam_app_id="1", title="以前の所有ゲーム",
            store_url="https://store.steampowered.com/app/1/", owned=True,
            wishlisted=True, steam_synced_at="2026-08-01T00:00:00+00:00",
        ).validated()
        db.save_game_observation(first, db_path=self.db_path)
        current = game_information.GameRecord(
            steam_app_id="2", title="現在の所有ゲーム",
            store_url="https://store.steampowered.com/app/2/", owned=True,
            steam_synced_at="2026-08-16T00:00:00+00:00",
        ).validated()
        db.save_owned_games_snapshot([current], self.db_path)
        with closing(db.connect(self.db_path)) as connection:
            old = connection.execute("SELECT owned,wishlisted FROM games WHERE steam_app_id='1'").fetchone()
            new = connection.execute("SELECT owned FROM games WHERE steam_app_id='2'").fetchone()
        self.assertEqual((old["owned"], old["wishlisted"]), (0, 1))
        self.assertEqual(new["owned"], 1)

    def test_owned_sync_failure_does_not_discard_weekly_candidates(self) -> None:
        def failed_ownership(_key, _steam_id):
            raise game_information.GameInformationError("認証失敗")

        secrets = {
            "STEAM_WEB_API_KEY": "test-key",
            "STEAM_ID64": "76561198000000000",
            "GEMINI_API_KEY": "",
        }
        with patch(
            "admin.game_scheduling.game_collection._environment_secret",
            side_effect=lambda name: secrets.get(name, ""),
        ):
            result = game_scheduling.process_due_weekly_collection(
                self.db_path,
                now=datetime(2026, 8, 15, tzinfo=timezone.utc),
                token="test-token",
                collector=lambda *_args, **_kwargs: self.result(),
                ownership_fetcher=failed_ownership,
            )
        self.assertEqual(result, "partial")
        self.assertEqual(db.game_information_summary(self.db_path)["games"], 1)


if __name__ == "__main__":
    unittest.main()

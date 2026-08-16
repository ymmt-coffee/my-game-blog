from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from admin import db, editorial_explanations, game_information


class EditorialExplanationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temporary.name) / "admin.sqlite3"
        db.initialize(self.db_path)
        game = game_information.GameRecord(
            steam_app_id="123456", title="候補ゲーム",
            store_url="https://store.steampowered.com/app/123456/",
            japan_availability="available", japanese_support="confirmed", single_player="yes",
        ).validated()
        db.save_game_observation(game, db_path=self.db_path)
        candidate = game_information.CandidateRecord(
            id="2026-W33-123456-new_release", steam_app_id="123456", cycle_key="2026-W33",
            candidate_kind="new_release", status="active", interest_score=0,
            momentum_score=15, review_score=0, price_score=5, diversity_score=10,
        ).validated()
        db.save_game_candidate(candidate, self.db_path)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_only_public_candidate_fields_are_sent_and_response_is_saved(self) -> None:
        captured = {}

        class Interactions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return type("Response", (), {"output_text": json.dumps({"items": [{
                    "number": 1, "explanation": "固定採点をもとに、プレイ候補として確認する価値があります。",
                    "suitable_for": "play",
                }]}, ensure_ascii=False)})()

        class Client:
            def __init__(self, api_key):
                captured["has_key"] = bool(api_key)
                self.interactions = Interactions()

            def close(self):
                captured["closed"] = True

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True):
            count = editorial_explanations.generate(self.db_path, Client)
        self.assertEqual(count, 1)
        self.assertNotIn("123456", captured["input"])
        self.assertNotIn("test-key", captured["input"])
        self.assertFalse(captured.get("store", True))
        self.assertTrue(captured["closed"])
        self.assertEqual(db.list_candidate_explanations(self.db_path)[0]["suitable_for"], "play")

    def test_invalid_ai_response_does_not_replace_existing_explanation(self) -> None:
        db.save_candidate_explanations("2026-W33", [{
            "steam_app_id": "123456", "explanation": "既存の安全な説明を保持します。十分な文字数があります。",
            "suitable_for": "hold",
        }], "fake", self.db_path)
        with self.assertRaises(game_information.GameInformationError):
            editorial_explanations.validate_response({"items": []}, ["123456"])
        self.assertEqual(db.list_candidate_explanations(self.db_path)[0]["suitable_for"], "hold")


if __name__ == "__main__":
    unittest.main()

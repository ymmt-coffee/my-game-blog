from __future__ import annotations

import unittest
import json
from datetime import date

from admin import game_collection
from admin.game_information import GameInformationError


class GameCollectionTests(unittest.TestCase):
    def test_readiness_never_exposes_secret_values(self) -> None:
        readiness = game_collection.collection_readiness({
            "APIFY_API_TOKEN": "secret-token", "APIFY_ACTOR_ID": "owner/actor",
            "STEAM_WEB_API_KEY": "steam-secret", "STEAM_ID64": "123",
        })
        self.assertTrue(readiness.trial_ready)
        self.assertTrue(readiness.ownership_sync_ready)
        self.assertNotIn("secret", repr(readiness))

    def test_rss_and_atom_keep_only_small_metadata_and_extract_app_id(self) -> None:
        rss = b'''<?xml version="1.0"?><rss><channel><item><title>Game News</title>
        <link>https://example.com/news</link><description><![CDATA[<p>Steam https://store.steampowered.com/app/123456/Game/</p>]]></description>
        <pubDate>2026-08-15T01:00:00+00:00</pubDate></item></channel></rss>'''
        item = game_collection.parse_feed(rss, "Media", 10)[0]
        self.assertEqual(item.steam_app_id, "123456")
        self.assertEqual(item.published_at, "2026-08-15T01:00:00+00:00")
        self.assertNotIn("<p>", item.summary or "")
        atom = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Atom News</title>
        <link href="https://example.com/atom"/><summary>summary</summary></entry></feed>'''
        self.assertEqual(game_collection.parse_feed(atom, "Media")[0].url, "https://example.com/atom")

    def test_feed_limits_and_invalid_xml_are_rejected(self) -> None:
        with self.assertRaises(GameInformationError):
            game_collection.parse_feed(b"x" * (game_collection.MAX_FEED_BYTES + 1), "Media")
        with self.assertRaises(GameInformationError):
            game_collection.parse_feed(b"not xml", "Media")
        with self.assertRaises(GameInformationError):
            game_collection.trial_items(list(range(11)), 11)

    def test_steam_japan_response_is_normalized(self) -> None:
        payload = {"123456": {"success": True, "data": {
            "steam_appid": 123456, "name": "Test Game", "is_free": False,
            "supported_languages": "English, Japanese, 日本語",
            "categories": [{"description": "Single-player"}],
            "developers": ["Studio"], "publishers": ["Publisher"],
            "website": "https://example.com/game",
            "release_date": {"coming_soon": False, "date": "15 Aug, 2026"},
            "price_overview": {"currency": "JPY", "initial": 300000, "final": 240000, "discount_percent": 20},
        }}}
        game, price = game_collection.parse_steam_store_response("123456", payload, "2026-08-15T00:00:00+00:00")
        self.assertEqual((game["japanese_support"], game["single_player"]), ("confirmed", "yes"))
        self.assertEqual(price["current_price"], 2400)

    def test_failed_or_wrong_steam_response_is_rejected(self) -> None:
        with self.assertRaises(GameInformationError):
            game_collection.parse_steam_store_response("123", {"123": {"success": False}})

    def test_apify_trial_uses_bearer_header_and_fixed_safe_limits(self) -> None:
        captured = {}
        payload = [{
            "success": True, "appId": 620, "name": "Portal 2", "appType": "game",
            "url": "https://store.steampowered.com/app/620/", "currency": "JPY",
            "initialPrice": 1200, "price": 1200, "discountPercent": 0,
            "releaseDate": "2011年4月18日", "developers": ["Valve"], "publishers": ["Valve"],
            "categories": ["シングルプレイヤー"], "scrapedAt": "2026-08-15T04:05:37+00:00",
            "isFree": False, "totalPositiveReviews": 90, "totalNegativeReviews": 10,
        }]

        def fake_transport(request, timeout):
            captured["url"] = request.full_url
            captured["authorization"] = request.headers.get("Authorization")
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return json.dumps(payload).encode("utf-8")

        results = game_collection.run_apify_trial("private-token", ("620",), fake_transport)
        self.assertNotIn("private-token", captured["url"])
        self.assertEqual(captured["authorization"], "Bearer private-token")
        self.assertEqual(captured["body"]["country"], "JP")
        self.assertEqual(captured["body"]["maxItems"], 1)
        self.assertFalse(captured["body"]["includeScreenshots"])
        self.assertEqual(results[0][0]["review_percent"], 90)

    def test_apify_trial_rejects_too_many_items_and_oversized_response(self) -> None:
        with self.assertRaises(GameInformationError):
            game_collection.run_apify_trial("token", tuple(str(i) for i in range(11)), lambda *_: b"[]")
        with self.assertRaises(GameInformationError):
            game_collection.run_apify_trial(
                "token", ("620",), lambda *_: b"x" * (game_collection.MAX_APIFY_RESPONSE_BYTES + 1)
            )

    def test_featured_candidates_select_five_new_and_five_sales_without_duplicates(self) -> None:
        payload = {
            "new_releases": {"items": [{"id": index} for index in range(1, 7)]},
            "specials": {"items": [
                {"id": 1, "discount_percent": 50},
                *({"id": index, "discount_percent": 20} for index in range(7, 13)),
            ]},
        }
        items = game_collection.parse_featured_candidates(payload)
        self.assertEqual(len(items), 10)
        self.assertEqual([item.candidate_kind for item in items].count("new_release"), 5)
        self.assertEqual([item.candidate_kind for item in items].count("sale"), 5)
        self.assertEqual(len({item.steam_app_id for item in items}), 10)

    def test_fixed_scoring_excludes_horror_and_keeps_verified_single_player(self) -> None:
        game = {
            "steam_app_id": "123", "title": "Game", "japanese_support": "confirmed",
            "single_player": "yes", "review_percent": 90, "review_count": 100,
            "free_to_play": False, "wishlisted": False, "release_date": "2026-08-15",
        }
        price = {"current_price": 5000, "discount_percent": 0}
        active = game_collection.score_candidate(
            game, price, "new_release", "2026-W33", "Action", today=date(2026, 8, 15)
        )
        excluded = game_collection.score_candidate(
            game, price, "new_release", "2026-W33", "Horror", today=date(2026, 8, 15)
        )
        self.assertEqual(active["status"], "active")
        self.assertGreater(active["total_score"], 0)
        self.assertEqual(excluded["status"], "excluded")
        self.assertIn("ホラー", str(excluded["exclusion_reason"]))


if __name__ == "__main__":
    unittest.main()

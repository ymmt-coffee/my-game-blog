from __future__ import annotations

import unittest
import json
from datetime import date
from unittest.mock import patch

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
            game_collection.run_apify_trial("token", tuple(str(i) for i in range(51)), lambda *_: b"[]")
        with self.assertRaises(GameInformationError):
            game_collection.run_apify_trial(
                "token", ("620",), lambda *_: b"x" * (game_collection.MAX_APIFY_RESPONSE_BYTES + 1)
            )

    def test_apify_monthly_usage_is_checked_without_token_in_url(self) -> None:
        captured = {}

        def transport(request, timeout):
            captured["url"] = request.full_url
            captured["authorization"] = request.headers.get("Authorization")
            return json.dumps({"data": {"totalUsageCreditsUsdAfterVolumeDiscount": 0.25}}).encode()

        usage = game_collection.apify_monthly_usage_usd("private-token", transport)
        self.assertEqual(usage, 0.25)
        self.assertNotIn("private-token", captured["url"])
        self.assertEqual(captured["authorization"], "Bearer private-token")

    def test_owned_games_use_official_endpoint_without_key_in_url(self) -> None:
        captured = {}

        def transport(request, timeout):
            captured["url"] = request.full_url
            captured["api_key"] = request.headers.get("X-webapi-key")
            captured["method"] = request.get_method()
            return json.dumps({"response": {"game_count": 1, "games": [
                {"appid": 620, "name": "Portal 2", "playtime_forever": 999},
            ]}}).encode()

        games = game_collection.fetch_owned_games("private-steam-key", "76561198000000000", transport)
        self.assertEqual(captured["method"], "GET")
        self.assertNotIn("private-steam-key", captured["url"])
        self.assertEqual(captured["api_key"], "private-steam-key")
        self.assertIn("input_json=", captured["url"])
        self.assertEqual(games[0]["steam_app_id"], "620")
        self.assertTrue(games[0]["owned"])
        self.assertNotIn("playtime", games[0])

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

    def test_weekly_featured_candidates_are_limited_to_ten_each(self) -> None:
        payload = {
            "new_releases": {"items": [{"id": index} for index in range(1, 16)]},
            "specials": {"items": [{"id": index, "discount_percent": 20} for index in range(16, 31)]},
        }
        items = game_collection.parse_featured_candidates(payload, game_collection.WEEKLY_STEAM_ITEM_LIMIT)
        self.assertEqual(len(items), 20)
        self.assertEqual([item.candidate_kind for item in items].count("new_release"), 10)
        self.assertEqual([item.candidate_kind for item in items].count("sale"), 10)

    def test_one_unavailable_steam_detail_does_not_stop_remaining_candidates(self) -> None:
        discovered = (
            game_collection.DiscoveredGame("1", "new_release"),
            game_collection.DiscoveredGame("2", "new_release"),
        )
        valid = {"2": {"success": True, "data": {
            "steam_appid": 2, "name": "Available Game", "is_free": False,
            "supported_languages": "Japanese", "categories": [{"description": "Single-player"}],
            "release_date": {"coming_soon": False, "date": "15 Aug, 2026"},
        }}}
        with (
            patch.object(game_collection, "parse_featured_candidates", return_value=discovered),
            patch.object(game_collection, "run_apify_trial", return_value=[]),
            patch.object(game_collection, "_load_json_response", side_effect=[{}, {"1": {"success": False}}, valid]),
        ):
            result = game_collection.run_candidate_trial(
                "token", today=date(2026, 8, 15), item_limit=2,
            )
        self.assertEqual([item.game["steam_app_id"] for item in result.items], ["2"])
        self.assertEqual(result.media_failures, ("Steam詳細1件",))

    def test_collection_can_keep_manual_trial_at_ten_items(self) -> None:
        captured = {}
        empty = game_collection.CandidateTrialResult((), 0)

        def candidate_trial(_token, **kwargs):
            captured["item_limit"] = kwargs["item_limit"]
            return empty

        with (
            patch.object(game_collection, "apify_monthly_usage_usd", return_value=0.0),
            patch.object(game_collection, "run_candidate_trial", side_effect=candidate_trial),
            patch.object(game_collection, "fetch_feed", return_value=[]),
        ):
            game_collection.run_weekly_collection("token", item_limit=game_collection.TRIAL_ITEM_LIMIT)
        self.assertEqual(captured["item_limit"], game_collection.TRIAL_ITEM_LIMIT)

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

    def test_media_headline_adds_bounded_momentum_without_article_body(self) -> None:
        game = {
            "steam_app_id": "123", "title": "Test Game", "japanese_support": "confirmed",
            "single_player": "yes", "free_to_play": False, "wishlisted": False,
        }
        candidate = game_collection.score_candidate(game, None, "sale", "2026-W33")
        trial = game_collection.CandidateTrialResult((
            game_collection.CandidateTrialItem(game, None, candidate),
        ), 1)
        feed = game_collection.FeedItem(
            "4Gamer", "Test Gameのセールが開始", "https://www.4gamer.net/games/001/G000001/1/",
            "2026-08-15T00:00:00+00:00", "短いRSS要約", None,
        )
        enriched = game_collection.add_media_momentum(trial, [feed]).items[0]
        self.assertEqual(enriched.candidate["momentum_score"], 15)
        self.assertEqual(enriched.media_items, (feed,))
        self.assertLessEqual(enriched.candidate["total_score"], 100)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from admin import db, scheduling, weekly_dashboard
from admin.app import create_app


class WeeklyDashboardTests(unittest.TestCase):
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

    def test_week_is_monday_to_sunday_and_article_is_listed(self) -> None:
        response = self.client.post("/articles/new", data={
            "csrf_token": self.app.state.csrf_token, "title": "今週の記事",
            "description": "トップ画面の確認", "article_type": "monthly_essay", "author": "やまもと",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        snapshot = weekly_dashboard.build(
            self.db_path, datetime(2026, 8, 19, 12, tzinfo=scheduling.JST),
        )
        self.assertEqual(snapshot["period"], "8/17〜8/23")
        self.assertEqual(snapshot["overall"], "進行中")
        self.assertEqual(snapshot["articles"][0]["display_title"], "今週の記事")

    def test_warning_has_highest_priority(self) -> None:
        self.client.post("/articles/new", data={
            "csrf_token": self.app.state.csrf_token, "title": "停止記事",
            "description": "予約エラー確認", "article_type": "monthly_essay", "author": "やまもと",
        })
        article = db.list_articles(self.db_path)[0]
        with closing(db.connect(self.db_path)) as connection:
            connection.execute("UPDATE articles SET schedule_error=? WHERE id=?", ("安全停止", article["id"]))
            connection.commit()
        snapshot = weekly_dashboard.build(self.db_path)
        self.assertEqual(snapshot["overall"], "要確認")
        self.assertEqual(snapshot["next_actions"][0]["kind"], "要確認")


if __name__ == "__main__":
    unittest.main()

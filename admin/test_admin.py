from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

from admin import db
from admin.app import create_app
from admin.run import HOST, PORT


class AdminPhaseBTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temporary.name) / "admin.sqlite3"
        self.app = create_app(db_path=self.db_path, testing=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_dashboard_and_all_menu_pages(self) -> None:
        with TestClient(self.app) as client:
            dashboard = client.get("/")
            self.assertEqual(dashboard.status_code, 200)
            self.assertIn('href="/articles">記事管理</a>', dashboard.text)
            self.assertNotIn("LOCAL ADMIN", dashboard.text)
            self.assertNotIn("localhost</span>", dashboard.text)
            article_page = client.get("/articles")
            self.assertIn("新規作成", article_page.text)
            self.assertIn("article-picker", article_page.text)
            for path in ("schedule", "editorial", "releases", "social", "analytics"):
                response = client.get(f"/{path}")
                self.assertEqual(response.status_code, 200)
                if path in {"schedule", "analytics"}:
                    self.assertIn("スケジュール" if path == "schedule" else "アクセス解析", response.text)
                else:
                    self.assertIn("準備中です", response.text)
            self.assertEqual(client.get("/settings").status_code, 200)

    def test_health_reports_local_scope(self) -> None:
        with TestClient(self.app) as client:
            self.assertEqual(
                client.get("/health").json(),
            {"status": "ok", "scope": "localhost_only", "phase": "H", "version": "phase-h-2"},
            )

    def test_unknown_host_is_rejected(self) -> None:
        with TestClient(self.app) as client:
            response = client.get("/", headers={"host": "example.com"})
            self.assertEqual(response.status_code, 400)

    def test_database_schema_and_safe_start_event(self) -> None:
        with TestClient(self.app):
            pass
        with closing(sqlite3.connect(self.db_path)) as connection:
            version = connection.execute("SELECT version FROM schema_migrations").fetchone()[0]
            event = connection.execute(
                "SELECT message_code, safe_message FROM app_events ORDER BY id DESC"
            ).fetchone()
        self.assertEqual(version, 1)
        with closing(sqlite3.connect(self.db_path)) as connection:
            versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
        self.assertEqual(versions, [1, 2, 3, 4, 5, 6])
        self.assertEqual(event, ("app_started", "管理画面を起動しました。"))

    def test_corrupt_database_stops_without_overwrite(self) -> None:
        self.db_path.write_bytes(b"not a sqlite database")
        original = self.db_path.read_bytes()
        with self.assertRaises(sqlite3.DatabaseError):
            db.initialize(self.db_path)
        self.assertEqual(self.db_path.read_bytes(), original)

    def test_server_binding_is_fixed_to_loopback(self) -> None:
        self.assertEqual(HOST, "127.0.0.1")
        self.assertEqual(PORT, 8765)


if __name__ == "__main__":
    unittest.main()

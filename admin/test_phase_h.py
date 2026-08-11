from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from admin import analytics, db
from admin.app import create_app


class PhaseHAnalyticsTests(unittest.TestCase):
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
        self.csrf = self.app.state.csrf_token

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)
        self.temporary.cleanup()

    def test_empty_dashboard_and_template(self) -> None:
        page = self.client.get("/analytics")
        self.assertEqual(page.status_code, 200)
        self.assertIn("閲覧数", page.text)
        self.assertIn("外部データ取得は未接続", page.text)
        template = self.client.get("/analytics/template.csv")
        self.assertEqual(template.status_code, 200)
        self.assertIn("date,path,views,visitors", template.text)

    def test_csv_import_displays_totals_and_comparison(self) -> None:
        today = date.today().isoformat()
        content = f"date,path,views,visitors\n{today},/posts/test/,12,8\n".encode()
        response = self.client.post("/analytics/import", data={
            "csrf_token": self.csrf, "source": "manual",
        }, files={"file": ("analytics.csv", content, "text/csv")}, follow_redirects=False)
        self.assertEqual(response.status_code, 303, response.text)
        page = self.client.get("/analytics?days=30")
        self.assertIn("/posts/test/", page.text)
        self.assertIn(">12<", page.text)
        self.assertIn(">8<", page.text)
        self.assertIn("analytics.csv", page.text)

    def test_same_source_day_and_path_are_replaced_not_added(self) -> None:
        today = date.today().isoformat()
        for views in (10, 15):
            content = f"date,path,views,visitors\n{today},/posts/test/,{views},7\n".encode()
            response = self.client.post("/analytics/import", data={
                "csrf_token": self.csrf, "source": "manual",
            }, files={"file": ("analytics.csv", content, "text/csv")}, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
        summary = db.analytics_summary(today, today, self.db_path)
        self.assertEqual(summary["views"], 15)
        self.assertEqual(summary["visitors"], 7)

    def test_invalid_csv_is_rejected_without_rows(self) -> None:
        content = b"date,path,views,visitors\n2026-08-11,/posts/test/?private=1,10,8\n"
        response = self.client.post("/analytics/import", data={
            "csrf_token": self.csrf, "source": "manual",
        }, files={"file": ("bad.csv", content, "text/csv")})
        self.assertEqual(response.status_code, 400)
        self.assertIn("ページパス", response.text)
        summary = db.analytics_summary("2026-08-01", "2026-08-31", self.db_path)
        self.assertEqual(summary["views"], 0)

    def test_parser_rejects_duplicate_and_extra_personal_data_is_not_stored(self) -> None:
        duplicate = b"date,path,views,visitors\n2026-08-11,/a/,1,1\n2026-08-11,/a/,2,1\n"
        with self.assertRaises(analytics.AnalyticsError):
            analytics.parse_csv(duplicate)
        rows = analytics.parse_csv(b"date,path,views,visitors,ip_address\n2026-08-11,/a/,1,1,192.0.2.1\n")
        self.assertNotIn("ip_address", rows[0])

    def test_periods_do_not_overlap(self) -> None:
        start, end, previous_start, previous_end = analytics.period(30, today=date(2026, 8, 11))
        self.assertEqual(start, date(2026, 7, 13))
        self.assertEqual(previous_end, start - timedelta(days=1))
        self.assertEqual((end - start).days, 29)
        self.assertEqual((previous_end - previous_start).days, 29)


if __name__ == "__main__":
    unittest.main()

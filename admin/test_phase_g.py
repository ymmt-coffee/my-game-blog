from __future__ import annotations

import re
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from admin import articles, db, publishing, scheduling
from admin.app import create_app


class PhaseGSchedulingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "state" / "admin.sqlite3"
        self.content = self.root / "content" / "articles"
        self.state = self.root / "state"
        self.app = create_app(
            db_path=self.db_path, content_root=self.content, state_root=self.state,
            legacy_root=self.root / "legacy", testing=True,
        )
        self.context = TestClient(self.app)
        self.client = self.context.__enter__()
        self.csrf = self.app.state.csrf_token
        created = self.client.post("/articles/new", data={
            "csrf_token": self.csrf, "title": "予約テスト", "article_type": "play_note",
            "author": "やまもと", "description": "予約公開を確認する記事です。",
            "play_time": "2時間", "game_completed": "false",
        }, follow_redirects=False)
        self.assertEqual(created.status_code, 303)
        self.record = db.list_articles(self.db_path)[0]
        self.article_id = str(self.record["id"])

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)
        self.temporary.cleanup()

    def _reserve(self) -> str:
        future = (datetime.now(scheduling.JST) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        article = articles.read_article(Path(str(self.record["source_path"])), self.article_id, str(self.record["slug"]))
        prepared = self.state / "publish-prepared" / self.article_id / article.file_hash
        prepared.mkdir(parents=True)
        (prepared / "index.md").write_text("---\ndraft: false\n---\n", encoding="utf-8")
        with patch("admin.app.publishing.prepublish_check", return_value=(publishing.CheckResult((), ()), prepared)):
            checked = self.client.post(f"/articles/{self.article_id}/schedule/check", data={
                "csrf_token": self.csrf, "scheduled_at": future,
            })
        self.assertEqual(checked.status_code, 200, checked.text)
        self.assertIn("予約の最終確認", checked.text)
        fields = dict(re.findall(r'name="(attempt_id|approval_token|scheduled_at)" value="([^"]+)"', checked.text))
        confirmed = self.client.post(f"/articles/{self.article_id}/schedule/confirm", data={
            "csrf_token": self.csrf, **fields,
        }, follow_redirects=False)
        self.assertEqual(confirmed.status_code, 303, confirmed.text)
        return fields["scheduled_at"]

    def test_schedule_confirmation_and_cancel(self) -> None:
        scheduled_at = self._reserve()
        record = db.get_article(self.article_id, self.db_path)
        self.assertEqual(record["state"], "scheduled")
        self.assertEqual(record["scheduled_at"], scheduled_at)
        page = self.client.get(f"/articles/{self.article_id}/edit")
        self.assertIn("公開予約済み", page.text)
        cancelled = self.client.post(f"/articles/{self.article_id}/schedule/cancel", data={
            "csrf_token": self.csrf,
        }, follow_redirects=False)
        self.assertEqual(cancelled.status_code, 303)
        self.assertEqual(db.get_article(self.article_id, self.db_path)["state"], "ready")

    def test_schedule_check_commits_current_editor_values(self) -> None:
        record = db.get_article(self.article_id, self.db_path)
        article = articles.read_article(Path(str(record["source_path"])), self.article_id, str(record["slug"]))
        future = (datetime.now(scheduling.JST) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        prepared = self.state / "publish-prepared" / self.article_id / "placeholder"
        with patch("admin.app.publishing.prepublish_check") as check:
            def checked(saved_article, *_args):
                target = self.state / "publish-prepared" / self.article_id / saved_article.file_hash
                target.mkdir(parents=True)
                return publishing.CheckResult((), ()), target
            check.side_effect = checked
            response = self.client.post(f"/articles/{self.article_id}/schedule/check", data={
                "csrf_token": self.csrf, "scheduled_at": future,
                "title": "予約時に保存したタイトル", "description": "予約操作で確定保存します。",
                "article_type": "play_note", "play_time": "3時間", "game_completed": "false",
                "body": "予約ボタンを押した時点の本文です。",
                "expected_hash": article.file_hash, "revision": record["revision"], "tab_id": "phase-g-tab",
            })
        self.assertEqual(response.status_code, 200, response.text)
        saved_record = db.get_article(self.article_id, self.db_path)
        saved = articles.read_article(Path(str(saved_record["source_path"])), self.article_id, str(saved_record["slug"]))
        self.assertEqual(saved.metadata["title"], "予約時に保存したタイトル")
        self.assertIn("予約ボタンを押した時点", saved.body)
        self.assertEqual(saved_record["state"], "ready")

    def test_calendar_has_month_week_and_reserved_article(self) -> None:
        self._reserve()
        month = self.client.get("/schedule?view=month")
        week = self.client.get("/schedule?view=week")
        self.assertIn("予約テスト", month.text)
        self.assertIn("予約", month.text)
        self.assertIn("calendar-grid week", week.text)

    def test_due_schedule_publishes_only_matching_snapshot(self) -> None:
        self._reserve()
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
        with closing(db.connect(self.db_path)) as connection:
            connection.execute("UPDATE articles SET scheduled_at=? WHERE id=?", (past, self.article_id))
            connection.commit()
        with patch("admin.scheduling.publishing.publish_article", return_value=("abc123", "https://example.invalid")) as publish:
            result = scheduling.process_due_schedules(self.db_path, self.state, lambda *args, **kwargs: None)
        self.assertEqual(result, [(self.article_id, "published")])
        publish.assert_called_once()
        self.assertEqual(db.get_article(self.article_id, self.db_path)["state"], "published")

    def test_changed_snapshot_is_stopped_and_returned_to_ready(self) -> None:
        self._reserve()
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
        with closing(db.connect(self.db_path)) as connection:
            connection.execute("UPDATE articles SET scheduled_at=?,scheduled_file_hash='different' WHERE id=?", (past, self.article_id))
            connection.commit()
        with patch("admin.scheduling.publishing.publish_article") as publish:
            result = scheduling.process_due_schedules(self.db_path, self.state, lambda *args, **kwargs: None)
        self.assertEqual(result, [(self.article_id, "failed")])
        publish.assert_not_called()
        record = db.get_article(self.article_id, self.db_path)
        self.assertEqual(record["state"], "ready")
        self.assertIn("原稿が変更", str(record["schedule_error"]))

    def test_past_datetime_is_rejected(self) -> None:
        past = (datetime.now(scheduling.JST) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M")
        response = self.client.post(f"/articles/{self.article_id}/schedule/check", data={
            "csrf_token": self.csrf, "scheduled_at": past,
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("現在より後", response.text)

    def test_confirmed_datetime_cannot_be_changed(self) -> None:
        future = (datetime.now(scheduling.JST) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        article = articles.read_article(Path(str(self.record["source_path"])), self.article_id, str(self.record["slug"]))
        prepared = self.state / "publish-prepared" / self.article_id / article.file_hash
        prepared.mkdir(parents=True)
        with patch("admin.app.publishing.prepublish_check", return_value=(publishing.CheckResult((), ()), prepared)):
            checked = self.client.post(f"/articles/{self.article_id}/schedule/check", data={
                "csrf_token": self.csrf, "scheduled_at": future,
            })
        fields = dict(re.findall(r'name="(attempt_id|approval_token|scheduled_at)" value="([^"]+)"', checked.text))
        fields["scheduled_at"] = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(timespec="seconds")
        response = self.client.post(f"/articles/{self.article_id}/schedule/confirm", data={
            "csrf_token": self.csrf, **fields,
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("予約日時と一致", response.text)
        self.assertEqual(db.get_article(self.article_id, self.db_path)["state"], "ready")


if __name__ == "__main__":
    unittest.main()

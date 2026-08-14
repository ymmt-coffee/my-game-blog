from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from admin import articles, db, social
from admin.app import create_app


class PhaseISocialTests(unittest.TestCase):
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
        article_id, path, digest = articles.create_article_files(
            self.content_root, "20260812-001", "テスト記事", "monthly_essay", "やまもと", "記事の概要です。",
        )
        db.create_article(article_id, path.name, "monthly_essay", str(path.resolve()), digest, self.db_path)
        db.mark_published(article_id, digest, self.db_path)
        self.article_id = article_id

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)
        self.temporary.cleanup()

    def test_draft_review_and_manual_post_record_without_external_send(self) -> None:
        page = self.client.get("/social")
        self.assertIn("当面はXだけで運用します", page.text)
        self.assertNotIn('name="platform"', page.text)
        response = self.client.post(
            "/social/drafts", data={"csrf_token": self.csrf, "article_id": self.article_id},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        draft = db.list_social_drafts(self.db_path)[0]
        self.assertIn("テスト記事", str(draft["message"]))
        self.assertIn(social.article_url("20260812-001"), str(draft["message"]))

        response = self.client.post(
            f"/social/drafts/{draft['id']}/review", data={"csrf_token": self.csrf},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(db.get_social_draft(str(draft["id"]), self.db_path)["status"], "reviewed")

        response = self.client.post(
            f"/social/drafts/{draft['id']}/posted",
            data={"csrf_token": self.csrf, "posted_url": ""},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        posted = db.get_social_draft(str(draft["id"]), self.db_path)
        self.assertEqual(posted["status"], "posted")
        self.assertEqual(posted["platform"], "X")

    def test_changed_article_stops_review(self) -> None:
        self.client.post("/social/drafts", data={"csrf_token": self.csrf, "article_id": self.article_id})
        draft = db.list_social_drafts(self.db_path)[0]
        index = self.content_root / "20260812-001" / "index.md"
        index.write_text(index.read_text(encoding="utf-8") + "\n変更\n", encoding="utf-8")
        response = self.client.post(
            f"/social/drafts/{draft['id']}/review", data={"csrf_token": self.csrf},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("記事が変更されています", response.text)
        self.assertEqual(db.get_social_draft(str(draft["id"]), self.db_path)["status"], "draft")

    def test_invalid_post_url_is_rejected(self) -> None:
        with self.assertRaises(social.SocialError):
            social.validate_posted_url("javascript:alert(1)")

    def test_x_draft_is_trimmed_to_raw_character_limit(self) -> None:
        message = social.generate_message("記事タイトル", "概要" * 300, "20260812-001")
        self.assertLessEqual(len(message), 280)
        self.assertIn("…", message)
        self.assertTrue(message.endswith(social.article_url("20260812-001")))


if __name__ == "__main__":
    unittest.main()

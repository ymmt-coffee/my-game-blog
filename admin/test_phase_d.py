from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import frontmatter
from fastapi.testclient import TestClient

from admin import article_templates, articles, db
from admin.app import create_app


class PhaseDTemplateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "state" / "admin.sqlite3"
        self.content_root = self.root / "content" / "articles"
        self.state_root = self.root / "state"
        self.app = create_app(
            db_path=self.db_path, content_root=self.content_root,
            state_root=self.state_root, legacy_root=self.root / "legacy", testing=True,
        )
        self.context = TestClient(self.app)
        self.client = self.context.__enter__()
        self.csrf = self.app.state.csrf_token

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)
        self.temporary.cleanup()

    def create(self, article_type: str, slug: str) -> tuple[dict[str, object], frontmatter.Post]:
        data = {
            "csrf_token": self.csrf, "title": "日本語：『特別』な記事", "slug": slug,
            "article_type": article_type, "author": "やまもと", "description": "日本語の概要：安全に保存します。",
            "play_time": "12時間" if article_type == "play_note" else "",
        }
        response = self.client.post("/articles/new", data=data, follow_redirects=False)
        self.assertEqual(response.status_code, 303, response.text)
        record = db.get_article_by_slug(slug, self.db_path)
        self.assertIsNotNone(record)
        post = frontmatter.load(self.content_root / slug / "index.md")
        return record, post

    def test_three_types_create_distinct_valid_markdown_templates(self) -> None:
        expected_heading = {
            "play_note": "## 今回遊んだところ",
            "weekly_picks": "## 1. ゲームタイトル",
            "monthly_essay": "## 今月のテーマ",
        }
        for article_type, heading in expected_heading.items():
            with self.subTest(article_type=article_type):
                _record, post = self.create(article_type, article_type.replace("_", "-"))
                self.assertEqual(post.metadata["article_type"], article_type)
                self.assertEqual(post.metadata["title"], "日本語：『特別』な記事")
                self.assertEqual(article_templates.validate_metadata(dict(post.metadata)), [])
                self.assertIn(heading, post.content)
                if article_type == "play_note":
                    self.assertEqual(post.metadata["play_time"], "12時間")
                else:
                    self.assertNotIn("play_time", post.metadata)

    def test_play_note_requires_play_time_but_other_types_do_not(self) -> None:
        response = self.client.post("/articles/new", data={
            "csrf_token": self.csrf, "title": "不足", "slug": "missing-time", "article_type": "play_note",
            "author": "やまもと", "description": "概要", "play_time": "",
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse((self.content_root / "missing-time").exists())
        self.assertIn("プレイ時間", response.text)

    def test_edit_preserves_unknown_front_matter_and_yaml_special_text(self) -> None:
        record, _post = self.create("play_note", "keep-keys")
        index = self.content_root / "keep-keys" / "index.md"
        post = frontmatter.load(index)
        post.metadata["custom_key"] = "残す: #特別"
        data = articles.render_markdown(dict(post.metadata), post.content)
        articles.atomic_write(index, data)
        db.accept_external_change(str(record["id"]), articles.file_hash(index), int(record["revision"]), self.db_path)
        record = db.get_article(str(record["id"]), self.db_path)
        response = self.client.post(f'/articles/{record["id"]}/save', data={
            "csrf_token": self.csrf, "expected_hash": record["file_hash"], "revision": record["revision"],
            "tab_id": "phase-d-tab", "title": "引用: #記号", "description": "概要: #記号",
            "article_type": "play_note", "play_time": "13時間", "body": "日本語本文",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303, response.text)
        saved = frontmatter.load(index)
        self.assertEqual(saved.metadata["custom_key"], "残す: #特別")
        self.assertEqual(saved.metadata["title"], "引用: #記号")
        self.assertEqual(saved.metadata["play_time"], "13時間")

    def test_edit_page_reports_missing_required_fields_without_modifying_file(self) -> None:
        record, _post = self.create("weekly_picks", "inspection")
        index = self.content_root / "inspection" / "index.md"
        post = frontmatter.load(index)
        post.metadata["description"] = ""
        data = articles.render_markdown(dict(post.metadata), post.content)
        articles.atomic_write(index, data)
        db.accept_external_change(str(record["id"]), articles.file_hash(index), int(record["revision"]), self.db_path)
        before = index.read_bytes()
        page = self.client.get(f'/articles/{record["id"]}/edit')
        self.assertIn("未入力 1", page.text)
        self.assertIn('title="概要が未入力です。"', page.text)
        self.assertNotIn("必須項目：要確認", page.text)
        self.assertEqual(index.read_bytes(), before)

    def test_new_form_explains_templates_and_switches_play_time(self) -> None:
        page = self.client.get("/articles/new")
        self.assertIn("/static/template-form.js", page.text)
        self.assertIn("プレイログ", page.text)
        self.assertIn("新作・セール", page.text)
        self.assertIn("月刊コラム", page.text)
        self.assertIn("data-play-time", page.text)

    def test_inspection_rejects_invalid_date_and_metadata_types(self) -> None:
        metadata = article_templates.initial_metadata("題名", "weekly_picks", "著者", "概要")
        metadata["date"] = "2026/08/09"
        metadata["images"] = "image.jpg"
        metadata["draft"] = "true"
        messages = article_templates.validate_metadata(metadata)
        self.assertIn("公開日はYYYY-MM-DD形式で入力してください。", messages)
        self.assertIn("画像一覧の形式が正しくありません。", messages)
        self.assertIn("下書き設定の形式が正しくありません。", messages)


if __name__ == "__main__":
    unittest.main()

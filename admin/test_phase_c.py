from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from admin import articles, db
from admin.app import create_app


class PhaseCArticleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "state" / "admin.sqlite3"
        self.content_root = self.root / "content" / "articles"
        self.state_root = self.root / "state"
        self.legacy_root = self.root / "legacy"
        self.app = create_app(
            db_path=self.db_path,
            content_root=self.content_root,
            state_root=self.state_root,
            legacy_root=self.legacy_root,
            testing=True,
        )
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()
        self.csrf = self.app.state.csrf_token

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.temporary.cleanup()

    def create_article(self, slug: str = "sample-note") -> tuple[str, dict[str, object]]:
        response = self.client.post(
            "/articles/new",
            data={
                "csrf_token": self.csrf,
                "title": "テスト記事",
                "slug": slug,
                "article_type": "play_note",
                "author": "テスト作者",
                "description": "テスト記事の概要です。",
                "play_time": "3時間",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        record = db.get_article_by_slug(slug, self.db_path)
        self.assertIsNotNone(record)
        return str(record["id"]), record

    def test_create_article_keeps_markdown_as_canonical_file(self) -> None:
        article_id, record = self.create_article()
        index = self.content_root / "sample-note" / "index.md"
        self.assertTrue(index.is_file())
        self.assertTrue((index.parent / "images").is_dir())
        self.assertIn("draft: true", index.read_text(encoding="utf-8"))
        self.assertNotIn("ここから本文", Path(self.db_path).read_bytes().decode("utf-8", errors="ignore"))
        edit = self.client.get(f"/articles/{article_id}/edit")
        self.assertIn("テスト記事", edit.text)
        self.assertIn("article-picker-item active", edit.text)
        self.assertIn("/static/workspace.js", edit.text)
        self.assertLess(edit.text.index("手動保存"), edit.text.index('aria-label="本文"'))
        self.assertNotIn("アーカイブする", edit.text)
        self.assertEqual(record["state"], "draft")

    def test_new_article_uses_daily_sequential_slug(self) -> None:
        form = {
            "csrf_token": self.csrf, "title": "自動付番", "article_type": "play_note",
            "author": "テスト作者", "description": "自動付番の確認です。", "play_time": "1時間",
        }
        first = self.client.post("/articles/new", data=form, follow_redirects=False)
        second = self.client.post("/articles/new", data=form, follow_redirects=False)
        prefix = date.today().strftime("%Y%m%d")
        self.assertEqual(first.status_code, 303)
        self.assertEqual(second.status_code, 303)
        self.assertTrue((self.content_root / f"{prefix}-001" / "index.md").is_file())
        self.assertTrue((self.content_root / f"{prefix}-002" / "index.md").is_file())
        self.assertNotIn("name=\"slug\"", self.client.get("/articles/new").text)

    def test_article_picker_has_search(self) -> None:
        self.create_article()
        page = self.client.get("/articles")
        self.assertIn('id="article-search"', page.text)
        self.assertIn('data-search="テスト記事 sample-note"', page.text)
        self.assertIn('class="active" href="/articles?status=draft">下書き', page.text)
        self.assertIn('href="/articles?status=published">公開済', page.text)
        self.assertNotIn("既存原稿を確認", page.text)

    def test_article_picker_switches_draft_and_published_tabs(self) -> None:
        article_id, _record = self.create_article()
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute("UPDATE articles SET state='published',published_at=? WHERE id=?", (db.utc_now(), article_id))
            connection.commit()
        draft_page = self.client.get("/articles?status=draft")
        published_page = self.client.get("/articles?status=published")
        self.assertNotIn("テスト記事", draft_page.text)
        self.assertIn("テスト記事", published_page.text)
        self.assertIn('class="active" href="/articles?status=published">公開済', published_page.text)

    def test_manual_save_creates_history_and_increments_revision(self) -> None:
        article_id, record = self.create_article()
        response = self.client.post(
            f"/articles/{article_id}/save",
            data={
                "csrf_token": self.csrf,
                "expected_hash": record["file_hash"],
                "revision": record["revision"],
                "tab_id": "tab-12345678",
                "title": "更新タイトル",
                "description": "更新概要",
                "article_type": "play_note",
                "body": "更新した本文です。",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        updated = db.get_article(article_id, self.db_path)
        self.assertEqual(updated["revision"], 2)
        text = (self.content_root / "sample-note" / "index.md").read_text(encoding="utf-8")
        self.assertIn("更新した本文", text)
        self.assertEqual(len(articles.history_files(self.state_root, article_id)), 1)
        saved_page = self.client.get(f"/articles/{article_id}/edit?saved=1")
        self.assertIn("<h1>編集: 更新タイトル</h1>", saved_page.text)
        self.assertNotIn("<h1>編集: sample-note</h1>", saved_page.text)

    def test_published_edit_becomes_identified_update_draft(self) -> None:
        article_id, _record = self.create_article()
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute("UPDATE articles SET state='published',published_at=? WHERE id=?", (db.utc_now(), article_id))
            connection.commit()
        published = db.get_article(article_id, self.db_path)
        edit = self.client.get(f"/articles/{article_id}/edit")
        self.assertIn("公開済み記事を編集中", edit.text)
        self.assertIn("アーカイブする", edit.text)
        saved = self.client.post(f"/articles/{article_id}/save", data={
            "csrf_token": self.csrf, "expected_hash": published["file_hash"],
            "revision": published["revision"], "tab_id": "tab-12345678",
            "title": "公開記事の更新", "description": "更新概要", "article_type": "play_note",
            "play_time": "4時間", "body": "更新途中の本文",
        }, follow_redirects=False)
        self.assertEqual(saved.status_code, 303, saved.text)
        updated = db.get_article(article_id, self.db_path)
        self.assertEqual(updated["state"], "draft")
        self.assertEqual(updated["previous_state"], "published")
        update_page = self.client.get(f"/articles/{article_id}/edit")
        self.assertIn("公開記事の更新下書き", update_page.text)
        self.assertIn("現在の公開ページは旧版のまま", update_page.text)
        self.assertNotIn("アーカイブする", update_page.text)

    def test_autosave_does_not_modify_canonical_file(self) -> None:
        article_id, record = self.create_article()
        index = self.content_root / "sample-note" / "index.md"
        original = index.read_bytes()
        response = self.client.post(
            f"/api/articles/{article_id}/autosave",
            headers={"X-CSRF-Token": self.csrf},
            json={
                "expected_hash": record["file_hash"], "revision": record["revision"], "tab_id": "tab-12345678",
                "title": "自動保存", "description": "", "article_type": "play_note", "body": "自動保存本文",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(index.read_bytes(), original)
        self.assertTrue((self.state_root / "autosave" / article_id / "tab-12345678.md").is_file())

    def test_stale_tab_and_external_change_are_rejected(self) -> None:
        article_id, record = self.create_article()
        index = self.content_root / "sample-note" / "index.md"
        index.write_text(index.read_text(encoding="utf-8") + "\n外部変更", encoding="utf-8")
        response = self.client.post(
            f"/articles/{article_id}/save",
            data={
                "csrf_token": self.csrf, "expected_hash": record["file_hash"], "revision": record["revision"],
                "tab_id": "tab-12345678", "title": "上書き", "description": "", "article_type": "play_note", "body": "消してはいけない",
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("外部変更", index.read_text(encoding="utf-8"))

        actual_hash = articles.file_hash(index)
        accepted = self.client.post(
            f"/articles/{article_id}/accept-external",
            data={"csrf_token": self.csrf, "revision": record["revision"], "actual_hash": actual_hash},
            follow_redirects=False,
        )
        self.assertEqual(accepted.status_code, 303)
        self.assertEqual(db.get_article(article_id, self.db_path)["file_hash"], actual_hash)

    def test_image_upload_normalizes_japanese_name_and_rejects_duplicate(self) -> None:
        article_id, _record = self.create_article()
        first = self.client.post(
            f"/articles/{article_id}/images",
            data={"csrf_token": self.csrf}, files={"image": ("ゲーム 画面.JPG", b"fake-jpg", "image/jpeg")},
            follow_redirects=False,
        )
        self.assertEqual(first.status_code, 303, first.text)
        second = self.client.post(
            f"/articles/{article_id}/images",
            data={"csrf_token": self.csrf}, files={"image": ("ゲーム 画面.JPG", b"other", "image/jpeg")},
        )
        self.assertEqual(second.status_code, 400)
        saved_images = list((self.content_root / "sample-note" / "images").iterdir())
        self.assertEqual(len(saved_images), 1)
        self.assertEqual(saved_images[0].suffix, ".jpg")
        self.assertEqual(saved_images[0].read_bytes(), b"fake-jpg")
        image_name = saved_images[0].name
        markdown = f"![{saved_images[0].stem}](images/{image_name})"
        edit = self.client.get(f"/articles/{article_id}/edit")
        self.assertIn('class="image-thumb"', edit.text)
        self.assertIn(f'data-copy-markdown="{markdown}"', edit.text)
        self.assertIn('class="image-upload"', edit.text)
        served = self.client.get(f"/articles/{article_id}/images/{image_name}")
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served.content, b"fake-jpg")

    def test_unsupported_image_extension_is_rejected(self) -> None:
        article_id, _record = self.create_article()
        response = self.client.post(
            f"/articles/{article_id}/images",
            data={"csrf_token": self.csrf}, files={"image": ("not-image.txt", b"text", "text/plain")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(any((self.content_root / "sample-note" / "images").iterdir()))

    def test_archive_is_logical_and_restorable(self) -> None:
        article_id, _record = self.create_article()
        index = self.content_root / "sample-note" / "index.md"
        before = index.read_bytes()
        archived = self.client.post(f"/articles/{article_id}/archive", data={"csrf_token": self.csrf}, follow_redirects=False)
        self.assertEqual(archived.status_code, 303)
        self.assertEqual(db.get_article(article_id, self.db_path)["state"], "archived")
        self.assertEqual(index.read_bytes(), before)
        self.assertNotIn("テスト記事", self.client.get("/articles").text)
        settings = self.client.get("/settings")
        self.assertIn("削除した記事の復元", settings.text)
        self.assertIn("テスト記事", settings.text)
        self.assertIn("復元", settings.text)
        restored = self.client.post(f"/articles/{article_id}/restore", data={"csrf_token": self.csrf}, follow_redirects=False)
        self.assertEqual(restored.status_code, 303)
        self.assertEqual(db.get_article(article_id, self.db_path)["state"], "draft")

    def test_csrf_is_required_for_changes(self) -> None:
        response = self.client.post(
            "/articles/new",
            data={"title": "危険", "slug": "unsafe", "article_type": "play_note", "author": "x"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse((self.content_root / "unsafe").exists())

    def test_legacy_dry_run_writes_manifest_without_copy(self) -> None:
        legacy = self.legacy_root / "old-note"
        legacy.mkdir(parents=True)
        (legacy / "index.md").write_text("---\ntitle: 旧原稿\ndraft: true\n---\n本文\n", encoding="utf-8")
        response = self.client.get("/articles/migration")
        self.assertEqual(response.status_code, 200)
        self.assertIn("旧原稿", response.text)
        manifest = json.loads((self.state_root / "migrations" / "latest-dry-run.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["mode"], "dry-run")
        self.assertFalse((self.content_root / "old-note").exists())

    def test_database_can_rebuild_index_from_markdown(self) -> None:
        article_id, _record = self.create_article()
        self.client_context.__exit__(None, None, None)
        self.client_context = None
        self.db_path.unlink()
        rebuilt_app = create_app(db_path=self.db_path, content_root=self.content_root, state_root=self.state_root, legacy_root=self.legacy_root, testing=True)
        with TestClient(rebuilt_app):
            rebuilt = db.get_article_by_slug("sample-note", self.db_path)
        self.assertEqual(rebuilt["id"], article_id)

    def test_history_restore_opens_candidate_without_overwrite(self) -> None:
        article_id, record = self.create_article()
        index = self.content_root / "sample-note" / "index.md"
        original = index.read_bytes()
        saved = self.client.post(
            f"/articles/{article_id}/save",
            data={
                "csrf_token": self.csrf, "expected_hash": record["file_hash"], "revision": record["revision"],
                "tab_id": "tab-12345678", "title": "新しい版", "description": "", "article_type": "play_note", "body": "新しい本文",
            }, follow_redirects=False,
        )
        self.assertEqual(saved.status_code, 303)
        history = articles.history_files(self.state_root, article_id)[0]
        restored = self.client.post(
            f"/articles/{article_id}/history/{history.name}/restore",
            data={"csrf_token": self.csrf, "tab_id": "restore-12345678"}, follow_redirects=False,
        )
        self.assertEqual(restored.status_code, 303)
        self.assertIn("recovery=restore-12345678.md", restored.headers["location"])
        self.assertNotEqual(index.read_bytes(), original)
        candidate_page = self.client.get(restored.headers["location"])
        self.assertIn("復元候補を読み込みました", candidate_page.text)
        self.assertIn("今回遊んだところ", candidate_page.text)

    def tearDown(self) -> None:
        if self.client_context is not None:
            self.client_context.__exit__(None, None, None)
        self.temporary.cleanup()


if __name__ == "__main__":
    unittest.main()

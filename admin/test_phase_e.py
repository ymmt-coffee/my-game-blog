from __future__ import annotations

import shutil
import subprocess
import tempfile
import os
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from admin import articles, db, publishing
from admin.app import create_app
from tools.publishing import review_article


def response_with_finding() -> dict[str, object]:
    value = review_article.fake_response()
    value["overall_result"] = "1件確認してください"
    value["categories"][0]["findings"] = [{
        "severity": "low", "location": "冒頭", "reason": "表現を確認", "suggestion": "短くする",
    }]
    return value


class PhaseEPublishingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "state" / "admin.sqlite3"
        self.content = self.root / "content" / "articles"
        self.state = self.root / "state"
        self.commands: list[list[str]] = []

        def fake_supplier(_request):
            return response_with_finding()

        self.app = create_app(
            db_path=self.db_path, content_root=self.content, state_root=self.state,
            legacy_root=self.root / "legacy", testing=True, review_supplier=fake_supplier,
        )
        self.context = TestClient(self.app)
        self.client = self.context.__enter__()
        self.csrf = self.app.state.csrf_token
        created = self.client.post("/articles/new", data={
            "csrf_token": self.csrf, "title": "公開テスト", "slug": "phase-e-test",
            "article_type": "play_note", "author": "やまもと", "description": "公開機能のテスト記事です。",
            "play_time": "2時間",
        }, follow_redirects=False)
        self.assertEqual(created.status_code, 303, created.text)
        self.record = db.get_article_by_slug("phase-e-test", self.db_path)
        self.article_id = str(self.record["id"])

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)
        self.temporary.cleanup()

    def test_ai_review_is_hidden_and_disabled(self) -> None:
        index = self.content / "phase-e-test" / "index.md"
        before = index.read_bytes()
        edit = self.client.get(f"/articles/{self.article_id}/edit")
        self.assertNotIn("AI校正", edit.text)
        result = self.client.post(f"/articles/{self.article_id}/review", data={"csrf_token": self.csrf}, follow_redirects=False)
        self.assertEqual(result.status_code, 400, result.text)
        self.assertIn("現在停止", result.text)
        self.assertEqual(index.read_bytes(), before)
        report, structured = publishing.review_paths(self.state, self.article_id)
        self.assertFalse(report.exists())
        self.assertFalse(structured.exists())
        self.assertFalse((index.parent / "review-report.md").exists())

    def test_ai_review_decision_endpoint_is_disabled(self) -> None:
        response = self.client.post(f"/articles/{self.article_id}/review/decision", data={
            "csrf_token": self.csrf, "finding_key": "typos:0", "decision": "accepted",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 400)
        self.assertIn("現在停止", response.text)

    def test_changed_article_invalidates_review_and_blocks_prepublish(self) -> None:
        index = self.content / "phase-e-test" / "index.md"
        index.write_bytes(index.read_bytes() + b"\nchanged\n")
        response = self.client.post(f"/articles/{self.article_id}/prepublish", data={"csrf_token": self.csrf})
        self.assertEqual(response.status_code, 400)
        self.assertIn("外部変更", response.text)

    def test_prepublish_confirmation_is_rendered_as_html(self) -> None:
        response = self.client.post(f"/articles/{self.article_id}/prepublish", data={"csrf_token": self.csrf})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/html"))
        self.assertTrue(response.text.startswith("<!doctype html>"))
        self.assertIn("投稿の最終確認", response.text)

    def test_newer_autosave_requires_manual_save_before_prepublish(self) -> None:
        article = articles.read_article(self.content / "phase-e-test", self.article_id, "phase-e-test")
        autosave = articles.save_autosave(self.state, self.article_id, "autosave-12345678", b"unsaved changes")
        future = time.time() + 2
        os.utime(autosave, (future, future))
        response = self.client.post(f"/articles/{self.article_id}/prepublish", data={"csrf_token": self.csrf})
        self.assertEqual(response.status_code, 400)
        self.assertIn("手動保存されていない編集内容", response.text)
        self.assertEqual(db.get_article(self.article_id, self.db_path)["state"], "draft")
        edit = self.client.get(f"/articles/{self.article_id}/edit")
        self.assertIn("履歴・復元から自動保存内容を確認", edit.text)

    def test_precommit_failure_restores_published_update_draft(self) -> None:
        record = db.get_article(self.article_id, self.db_path)
        with closing(db.connect(self.db_path)) as connection:
            connection.execute("UPDATE articles SET state='ready',published_at=? WHERE id=?", (db.utc_now(), self.article_id))
            connection.commit()
        db.restore_after_precommit_publish_failure(self.article_id, str(record["file_hash"]), self.db_path)
        restored = db.get_article(self.article_id, self.db_path)
        self.assertEqual(restored["state"], "draft")
        self.assertEqual(restored["previous_state"], "published")

    def test_hugo_preview_failure_does_not_modify_article(self) -> None:
        def failing_runner(args, **_kwargs):
            self.commands.append(args)
            return subprocess.CompletedProcess(args, 1, "", "failed")

        self.app.state.command_runner = failing_runner
        index = self.content / "phase-e-test" / "index.md"
        before = index.read_bytes()
        response = self.client.post(f"/articles/{self.article_id}/preview", data={"csrf_token": self.csrf})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Hugoプレビュー", response.text)
        self.assertEqual(index.read_bytes(), before)
        self.assertTrue(any(command[0] == "hugo" for command in self.commands))

    def test_publish_without_valid_approval_never_calls_git_or_network(self) -> None:
        called = []

        def forbidden_runner(args, **_kwargs):
            called.append(args)
            raise AssertionError("外部処理を呼んではいけません")

        self.app.state.command_runner = forbidden_runner
        response = self.client.post(f"/articles/{self.article_id}/publish", data={
            "csrf_token": self.csrf, "attempt_id": "missing", "approval_token": "x", "confirm_slug": "phase-e-test",
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(called, [])

    def test_mixed_staged_paths_stop_before_commit_and_push(self) -> None:
        original_root, original_posts = publishing.PROJECT_ROOT, publishing.PUBLIC_POSTS
        try:
            publishing.PROJECT_ROOT = self.root
            publishing.PUBLIC_POSTS = self.root / "blog" / "content" / "posts"
            source = self.root / "content" / "articles" / "safe-post"
            source.mkdir(parents=True)
            (source / "index.md").write_text("---\ntitle: x\n---\nbody\n", encoding="utf-8")
            prepared = self.root / "prepared" / ("a" * 64)
            prepared.mkdir(parents=True)
            (prepared / "index.md").write_text("---\ndraft: false\n---\nbody\n", encoding="utf-8")
            article = articles.ArticleFile("id", "safe-post", source, {}, "body", "a" * 64)
            calls = []

            def runner(args, **_kwargs):
                calls.append(args)
                if args[:4] == ["git", "diff", "--cached", "--name-only"]:
                    return subprocess.CompletedProcess(args, 0, "content/articles/safe-post/index.md\nunrelated.txt\n", "")
                if args[:3] == ["git", "diff", "--cached"]:
                    return subprocess.CompletedProcess(args, 0, "", "")
                if args[:3] == ["git", "status", "--porcelain"]:
                    return subprocess.CompletedProcess(args, 0, "", "")
                return subprocess.CompletedProcess(args, 0, "", "")

            with self.assertRaises(publishing.PublishError):
                publishing.publish_article(article, prepared, runner)
            self.assertFalse(any(call[:2] == ["git", "commit"] for call in calls))
            self.assertFalse(any(call[:2] == ["git", "push"] for call in calls))
        finally:
            publishing.PROJECT_ROOT, publishing.PUBLIC_POSTS = original_root, original_posts

    def test_no_publish_diff_reports_manual_save_and_is_precommit_failure(self) -> None:
        original_root, original_posts = publishing.PROJECT_ROOT, publishing.PUBLIC_POSTS
        try:
            publishing.PROJECT_ROOT = self.root
            publishing.PUBLIC_POSTS = self.root / "blog/content/posts"
            source = self.root / "content/articles/no-diff"
            (source / "images").mkdir(parents=True)
            (source / "index.md").write_text("---\ntitle: x\n---\nbody\n", encoding="utf-8")
            prepared = self.root / "prepared" / ("e" * 64)
            prepared.mkdir(parents=True)
            (prepared / "index.md").write_text("---\ndraft: false\n---\nbody\n", encoding="utf-8")
            article = articles.ArticleFile("id", "no-diff", source, {}, "body", "e" * 64)

            def runner(args, **_kwargs):
                if args[:4] == ["git", "diff", "--cached", "--name-only"]:
                    return subprocess.CompletedProcess(args, 0, "", "")
                return subprocess.CompletedProcess(args, 0, "", "")

            with self.assertRaisesRegex(publishing.PublishError, "確定保存済みの変更がありません") as caught:
                publishing.publish_article(article, prepared, runner)
            self.assertTrue(caught.exception.before_commit)
        finally:
            publishing.PROJECT_ROOT, publishing.PUBLIC_POSTS = original_root, original_posts

    def test_review_report_in_article_is_never_staged(self) -> None:
        original_root, original_posts = publishing.PROJECT_ROOT, publishing.PUBLIC_POSTS
        try:
            publishing.PROJECT_ROOT = self.root
            publishing.PUBLIC_POSTS = self.root / "blog/content/posts"
            source = self.root / "content/articles/private-report"
            (source / "images").mkdir(parents=True)
            (source / "index.md").write_text("---\ntitle: x\n---\nbody\n", encoding="utf-8")
            (source / "review-report.md").write_text("private", encoding="utf-8")
            prepared = self.root / "prepared" / ("b" * 64)
            prepared.mkdir(parents=True)
            (prepared / "index.md").write_text("---\ndraft: false\n---\nbody\n", encoding="utf-8")
            article = articles.ArticleFile("id", "private-report", source, {}, "body", "b" * 64)
            calls = []
            def runner(args, **_kwargs):
                calls.append(args)
                return subprocess.CompletedProcess(args, 0, "", "")
            with self.assertRaises(publishing.PublishError):
                publishing.publish_article(article, prepared, runner)
            self.assertFalse(any(call[:2] == ["git", "add"] for call in calls))
        finally:
            publishing.PROJECT_ROOT, publishing.PUBLIC_POSTS = original_root, original_posts

    def test_successful_publish_uses_scoped_git_and_stubbed_pages(self) -> None:
        original_root, original_posts = publishing.PROJECT_ROOT, publishing.PUBLIC_POSTS
        try:
            publishing.PROJECT_ROOT = self.root
            publishing.PUBLIC_POSTS = self.root / "blog/content/posts"
            source = self.root / "content/articles/success-post"
            (source / "images").mkdir(parents=True)
            (source / "index.md").write_text("---\ntitle: x\n---\nbody\n", encoding="utf-8")
            prepared = self.root / "prepared" / ("c" * 64)
            prepared.mkdir(parents=True)
            (prepared / "index.md").write_text("---\ndraft: false\n---\nbody\n", encoding="utf-8")
            article = articles.ArticleFile("id", "success-post", source, {}, "body", "c" * 64)
            calls = []
            def runner(args, **_kwargs):
                calls.append(args)
                if args[:4] == ["git", "diff", "--cached", "--name-only"]:
                    return subprocess.CompletedProcess(args, 0, "content/articles/success-post/index.md\nblog/content/posts/success-post/index.md\n", "")
                if args[:3] == ["git", "diff", "--cached"]: return subprocess.CompletedProcess(args, 0, "", "")
                if args[:3] == ["git", "status", "--porcelain"]: return subprocess.CompletedProcess(args, 0, "", "")
                if args[:3] == ["git", "rev-parse", "HEAD"]: return subprocess.CompletedProcess(args, 0, "d" * 40 + "\n", "")
                if args[:3] == ["gh", "run", "list"]:
                    return subprocess.CompletedProcess(args, 0, '[{"status":"completed","conclusion":"success","url":"https://actions.example/run"}]', "")
                return subprocess.CompletedProcess(args, 0, "", "")
            class Response:
                status = 200
                def __enter__(self): return self
                def __exit__(self, *_args): return None
            with patch("admin.publishing.urlopen", return_value=Response()):
                sha, pages = publishing.publish_article(article, prepared, runner)
            self.assertEqual(sha, "d" * 40)
            self.assertEqual(pages, "https://actions.example/run")
            self.assertTrue(any(call[:2] == ["git", "commit"] for call in calls))
            self.assertTrue(any(call[:3] == ["git", "push", "origin"] for call in calls))
            add = next(call for call in calls if call[:2] == ["git", "add"])
            self.assertNotIn("content/articles/success-post", add)
            self.assertIn("content/articles/success-post/index.md", add)
        finally:
            publishing.PROJECT_ROOT, publishing.PUBLIC_POSTS = original_root, original_posts

    def test_unpublish_removes_only_public_copy_and_keeps_canonical(self) -> None:
        original_root, original_posts = publishing.PROJECT_ROOT, publishing.PUBLIC_POSTS
        try:
            publishing.PROJECT_ROOT = self.root
            publishing.PUBLIC_POSTS = self.root / "blog/content/posts"
            source = self.root / "content/articles/keep-source"
            source.mkdir(parents=True)
            (source / "index.md").write_text("---\ntitle: x\n---\nbody\n", encoding="utf-8")
            public = publishing.PUBLIC_POSTS / "keep-source"
            public.mkdir(parents=True)
            (public / "index.md").write_text("---\ndraft: false\n---\nbody\n", encoding="utf-8")
            article = articles.ArticleFile("id", "keep-source", source, {}, "body", "f" * 64)
            calls = []

            def runner(args, **_kwargs):
                calls.append(args)
                if args[:4] == ["git", "diff", "--cached", "--name-only"]:
                    return subprocess.CompletedProcess(args, 0, "blog/content/posts/keep-source/index.md\n", "")
                if args[:3] == ["git", "status", "--porcelain"]:
                    return subprocess.CompletedProcess(args, 0, "", "")
                if args[:3] == ["git", "rev-parse", "HEAD"]:
                    return subprocess.CompletedProcess(args, 0, "a" * 40 + "\n", "")
                if args[:3] == ["gh", "run", "list"]:
                    return subprocess.CompletedProcess(args, 0, '[{"status":"completed","conclusion":"success","url":"https://actions.example/run"}]', "")
                return subprocess.CompletedProcess(args, 0, "", "")

            class Response:
                status = 200
                def __enter__(self): return self
                def __exit__(self, *_args): return None

            with patch("admin.publishing.urlopen", return_value=Response()):
                sha, _pages = publishing.unpublish_article(article, runner)
            self.assertEqual(sha, "a" * 40)
            self.assertTrue(source.is_dir())
            self.assertTrue(any(call[:3] == ["git", "rm", "-r"] for call in calls))
            self.assertTrue(any(call[:2] == ["git", "commit"] for call in calls))
            self.assertTrue(any(call[:3] == ["git", "push", "origin"] for call in calls))
            self.assertFalse(any("content/articles/keep-source" in part for call in calls for part in call))
        finally:
            publishing.PROJECT_ROOT, publishing.PUBLIC_POSTS = original_root, original_posts


if __name__ == "__main__":
    unittest.main()

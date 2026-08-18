from __future__ import annotations

import unittest

from tools.security import check_staged_commit


class CommitSafetyInspectionTests(unittest.TestCase):
    def test_safe_article_is_allowed(self) -> None:
        data = b"---\ntitle: test\n---\nordinary article\n"
        self.assertEqual(check_staged_commit.inspect_path("content/articles/20260818-001/index.md", data), [])

    def test_review_report_is_blocked(self) -> None:
        findings = check_staged_commit.inspect_path("content/articles/example/review-report.md", b"private")
        self.assertTrue(any("review-report" in item.reason for item in findings))

    def test_local_database_path_is_blocked(self) -> None:
        findings = check_staged_commit.inspect_path("var/admin/admin.sqlite3", b"SQLite format")
        self.assertTrue(any("ローカル専用" in item.reason for item in findings))

    def test_private_key_is_blocked(self) -> None:
        findings = check_staged_commit.inspect_path("notes.txt", b"-----BEGIN " + b"PRIVATE KEY-----\nsecret")
        self.assertTrue(any("秘密鍵" in item.reason for item in findings))

    def test_api_tokens_are_blocked(self) -> None:
        samples = (
            b"token=" + b"ghp_" + b"abcdefghijklmnopqrstuvwxyz1234567890",
            b"key=" + b"AIza" + b"ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789",
            b"APIFY_API_TOKEN=" + b"apify_api_" + b"ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
            b"STEAM_WEB_API_KEY=" + b"0123456789abcdef" * 2,
        )
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertTrue(check_staged_commit.inspect_path("config.txt", sample))

    def test_real_windows_user_path_is_blocked_but_placeholder_is_allowed(self) -> None:
        self.assertTrue(check_staged_commit.inspect_path("docs/note.md", b"C:\\Users\\alice\\Documents\\project"))
        self.assertEqual(check_staged_commit.inspect_path("docs/note.md", b"C:\\Users\\<user>\\Documents\\project"), [])


if __name__ == "__main__":
    unittest.main()

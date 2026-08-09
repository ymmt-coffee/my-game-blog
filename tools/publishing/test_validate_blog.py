from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("validate_blog.py")


def write_post(root: Path, slug: str, metadata: str, body: str = "本文") -> Path:
    bundle = root / "posts" / slug
    bundle.mkdir(parents=True)
    path = bundle / "index.md"
    path.write_text(f"---\n{metadata}\n---\n\n{body}\n", encoding="utf-8")
    return path


class ValidateBlogTests(unittest.TestCase):
    def run_validator(self, content: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--content-dir", str(content), *extra],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )

    def test_valid_play_note_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            content = Path(temp_name) / "content"
            write_post(
                content,
                "sample",
                'title: Sample\ndate: 2026-08-02\nlastmod: 2026-08-02\ndraft: false\n'
                'description: Sample description\nimages: []\narticle_type: play_note\n'
                'play_time: "約5時間"\nprovided: false\nspoiler_warning: ""\nauthor: やまもと',
            )
            result = self.run_validator(content, "--article", "sample", "--production")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_required_field_stops(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            content = Path(temp_name) / "content"
            write_post(
                content,
                "missing",
                "title: Missing\ndate: 2026-08-02\ndraft: false\nimages: []\narticle_type: monthly_essay\nauthor: やまもと",
            )
            result = self.run_validator(content, "--article", "missing", "--production")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("description", result.stdout)
            self.assertIn("lastmod", result.stdout)

    def test_missing_image_broken_link_and_review_report_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            content = Path(temp_name) / "content"
            path = write_post(
                content,
                "broken",
                'title: Broken\ndate: 2026-08-02\nlastmod: 2026-08-02\ndraft: false\n'
                'description: Broken description\nimages: ["images/missing.png"]\n'
                'article_type: monthly_essay\nauthor: やまもと',
                "[存在しない記事](../missing/)\n\n![欠落](images/missing.png)",
            )
            (path.parent / "review-report.md").write_text("非公開", encoding="utf-8")
            result = self.run_validator(content, "--production")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("review-report.md", result.stdout)
            self.assertIn("参照画像がありません", result.stdout)
            self.assertIn("壊れた内部リンク", result.stdout)

    def test_published_test_content_stops(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            content = Path(temp_name) / "content"
            write_post(
                content,
                "accidental-test",
                "title: Test\ndate: 2026-08-02\ndraft: false\ntest_content: true",
            )
            result = self.run_validator(content, "--production")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("テスト用コンテンツ", result.stdout)


if __name__ == "__main__":
    unittest.main()

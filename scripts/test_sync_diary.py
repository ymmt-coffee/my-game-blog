from __future__ import annotations

import base64
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("sync_diary.py")
PROJECT_ROOT = SCRIPT.parent.parent


class SyncDiaryTests(unittest.TestCase):
    def run_sync(
        self,
        source: Path,
        output: Path,
        *extra: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--source",
                str(source),
                "--output",
                str(output),
                *extra,
            ],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )

    def test_page_bundle_copies_images_and_excludes_review_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            source = root / "source"
            output = root / "output"
            article = source / "sample-game"
            images = article / "images"
            images.mkdir(parents=True)
            (article / "index.md").write_text(
                "---\ntitle: Sample\ndraft: false\n---\n\n![[01.png|画面]]\n",
                encoding="utf-8",
            )
            (article / "review-report.md").write_text("非公開", encoding="utf-8")
            (images / "01.png").write_bytes(
                base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
                )
            )

            result = self.run_sync(source, output)

            self.assertEqual(result.returncode, 0, result.stderr)
            generated = output / "sample-game"
            self.assertTrue((generated / "index.md").is_file())
            self.assertTrue((generated / "images" / "01.png").is_file())
            self.assertNotIn("review-report", (generated / "index.md").read_text(encoding="utf-8"))
            self.assertFalse(any(output.rglob("review-report.md")))
            self.assertIn(
                "![画面](images/01.png)",
                (generated / "index.md").read_text(encoding="utf-8"),
            )
            content_root = root / "content"
            content_root.mkdir()
            output.rename(content_root / "posts")
            hugo_result = subprocess.run(
                [
                    "hugo",
                    "--renderToMemory",
                    "--minify",
                    "--contentDir",
                    str(content_root),
                ],
                cwd=PROJECT_ROOT,
                capture_output=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(hugo_result.returncode, 0, hugo_result.stderr)

    def test_missing_image_stops_without_creating_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            source = root / "source"
            output = root / "output"
            article = source / "broken-game"
            article.mkdir(parents=True)
            (article / "index.md").write_text(
                "---\ntitle: Broken\ndraft: false\n---\n\n![[missing.png]]\n",
                encoding="utf-8",
            )

            result = self.run_sync(source, output)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("参照画像が見つかりません", result.stderr)
            self.assertFalse((output / "broken-game").exists())

    def test_publish_requires_explicit_draft_false(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            source = root / "source"
            output = root / "output"
            article = source / "draft-game"
            article.mkdir(parents=True)
            (article / "index.md").write_text(
                "---\ntitle: Draft\ndraft: true\n---\n\n本文\n",
                encoding="utf-8",
            )

            result = self.run_sync(
                source,
                output,
                "--article",
                "draft-game",
                "--require-publishable",
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("draft: false", result.stderr)
            self.assertFalse((output / "draft-game").exists())

    def test_legacy_markdown_is_migrated_to_its_own_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            source = root / "source"
            output = root / "output"
            source.mkdir(parents=True)
            (source / "2026-08-01-old-post.md").write_text("旧記事", encoding="utf-8")

            result = self.run_sync(source, output)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((output / "2026-08-01-old-post" / "index.md").is_file())


if __name__ == "__main__":
    unittest.main()

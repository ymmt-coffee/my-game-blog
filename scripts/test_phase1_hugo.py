from __future__ import annotations

import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = PROJECT_ROOT / "scripts" / "validate_blog.py"


def solid_png(width: int, height: int) -> bytes:
    def chunk(name: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + name + payload + struct.pack(">I", zlib.crc32(name + payload) & 0xFFFFFFFF)

    row = b"\x00" + (b"\x70\x88\xa0" * width)
    raw = row * height
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def write_article(content: Path, slug: str, article_type: str, extra: str, body: str) -> Path:
    bundle = content / "posts" / slug
    bundle.mkdir(parents=True)
    images_field = "" if "images:" in extra else "images: []\n"
    (bundle / "index.md").write_text(
        "---\n"
        f'title: "{slug}"\n'
        "date: 2026-08-02T00:00:00+09:00\n"
        "lastmod: 2026-08-02T00:00:00+09:00\n"
        "draft: false\n"
        f'description: "{slug}の説明"\n'
        f"{images_field}"
        f"article_type: {article_type}\n"
        "spoiler_warning: \"\"\n"
        "provided: false\n"
        "author: やまもと\n"
        f"{extra}"
        "---\n\n"
        f"{body}\n",
        encoding="utf-8",
    )
    return bundle


class Phase1HugoTests(unittest.TestCase):
    def test_three_article_types_seo_images_and_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            content = root / "content"
            public = root / "public"

            for page in ("about", "privacy", "editorial-policy", "review-key-policy"):
                shutil.copytree(PROJECT_ROOT / "content" / page, content / page)

            play = write_article(
                content,
                "play-note-test",
                "play_note",
                'play_time: "約6時間"\nimages:\n  - images/hero.png\n',
                "![テスト画像](images/hero.png)",
            )
            images = play / "images"
            images.mkdir()
            (images / "hero.png").write_bytes(solid_png(1600, 900))
            write_article(content, "weekly-picks-test", "weekly_picks", "", "## 1\n\n## 2\n\n## 3\n\n## 4\n\n## 5")
            write_article(content, "monthly-essay-test", "monthly_essay", "", "静かな本文です。")

            draft = content / "posts" / "draft-test"
            draft.mkdir(parents=True)
            (draft / "index.md").write_text("---\ntitle: Draft\ndraft: true\n---\n", encoding="utf-8")

            build = subprocess.run(
                [
                    "hugo",
                    "--contentDir",
                    str(content),
                    "--destination",
                    str(public),
                    "--environment",
                    "production",
                    "--minify",
                    "--cleanDestinationDir",
                ],
                cwd=PROJECT_ROOT,
                capture_output=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)

            validation = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    "--content-dir",
                    str(content),
                    "--public-dir",
                    str(public),
                    "--production",
                ],
                capture_output=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)

            play_html = (public / "posts" / "play-note-test" / "index.html").read_text(encoding="utf-8")
            weekly_html = (public / "posts" / "weekly-picks-test" / "index.html").read_text(encoding="utf-8")
            monthly_html = (public / "posts" / "monthly-essay-test" / "index.html").read_text(encoding="utf-8")
            self.assertIn("約6時間", play_html)
            self.assertIn("完走したレビューではなく", play_html)
            self.assertIn("未プレイ作品", weekly_html)
            self.assertNotIn("article-disclosures", monthly_html)
            self.assertIn("<picture>", play_html)
            self.assertRegex(play_html, r'type="?image/webp"?')
            self.assertRegex(play_html, r'<img[^>]+width="?1440"?[^>]+height="?810"?')
            self.assertIn('property="og:image"', play_html)
            self.assertIn("twitter:card", play_html)
            self.assertIn("summary_large_image", play_html)
            self.assertIn("application/ld+json", play_html)
            self.assertFalse((public / "posts" / "draft-test").exists())
            self.assertTrue((public / "sitemap.xml").is_file())
            self.assertTrue((public / "robots.txt").is_file())
            self.assertTrue((public / "index.xml").is_file())


if __name__ == "__main__":
    unittest.main()

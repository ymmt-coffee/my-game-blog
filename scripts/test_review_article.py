from __future__ import annotations

import base64
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("review_article.py")
SYNC_SCRIPT = Path(__file__).with_name("sync_diary.py")
PROJECT_ROOT = SCRIPT.parent.parent
SPEC = importlib.util.spec_from_file_location("review_article", SCRIPT)
assert SPEC and SPEC.loader
review_article = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = review_article
SPEC.loader.exec_module(review_article)


def write_article(root: Path, slug: str, article_type: str = "monthly_essay", body: str = "日本語の本文です。") -> Path:
    article = root / slug
    article.mkdir(parents=True)
    play_time = 'play_time: "約5時間"\n' if article_type == "play_note" else ""
    (article / "index.md").write_text(
        "---\n"
        f'title: "{slug}"\n'
        "date: 2026-08-02\n"
        "lastmod: 2026-08-02\n"
        "draft: false\n"
        f'description: "{slug}の説明"\n'
        "images: []\n"
        f"article_type: {article_type}\n"
        f"{play_time}"
        'spoiler_warning: ""\n'
        "provided: false\n"
        "author: やまもと\n"
        "---\n\n"
        f"{body}\n",
        encoding="utf-8",
    )
    return article


def response_with_finding() -> dict[str, object]:
    categories = []
    for category_id, _ in review_article.CATEGORIES:
        findings = []
        if category_id == "typos":
            findings = [
                {
                    "severity": "low",
                    "location": "本文1文目",
                    "reason": "表記を確認すると読みやすくなります",
                    "suggestion": "修正案だけをここへ記録します",
                }
            ]
        categories.append({"id": category_id, "findings": findings})
    return {"overall_result": "要確認", "categories": categories, "user_checklist": ["提案を採用するか確認する"]}


class ReviewArticleTests(unittest.TestCase):
    def run_cli(self, source: Path, slug: str, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--source", str(source), "--article", slug, *extra],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )

    def test_three_article_types_create_all_six_categories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            source = Path(temp_name)
            for slug, article_type in (("play", "play_note"), ("picks", "weekly_picks"), ("essay", "monthly_essay")):
                article = write_article(source, slug, article_type)
                before = (article / "index.md").read_bytes()
                result = self.run_cli(source, slug, "--fake")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                report = (article / "review-report.md").read_text(encoding="utf-8")
                for _, heading in review_article.CATEGORIES:
                    self.assertIn(f"## {heading}", report)
                self.assertEqual(report.count("指摘なし"), 7)
                self.assertEqual((article / "index.md").read_bytes(), before)

    def test_utf8_hash_unchanged_and_suggestion_only_in_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            source = Path(temp_name)
            article = write_article(source, "日本語", body="珈琲を飲みながら遊びました。")
            before = (article / "index.md").read_bytes()
            response_path = source / "response.json"
            response_path.write_text(json.dumps(response_with_finding(), ensure_ascii=False), encoding="utf-8")
            result = self.run_cli(source, "日本語", "--response-file", str(response_path), "--method", "test-model")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((article / "index.md").read_bytes(), before)
            self.assertNotIn("修正案だけをここへ記録します", (article / "index.md").read_text(encoding="utf-8"))
            self.assertIn("修正案だけをここへ記録します", (article / "review-report.md").read_text(encoding="utf-8"))

    def test_failure_does_not_damage_body_or_existing_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            source = Path(temp_name)
            article = write_article(source, "safe")
            old_report = b"existing report\n"
            (article / "review-report.md").write_bytes(old_report)
            before = (article / "index.md").read_bytes()
            bad = source / "bad.json"
            bad.write_text("not-json", encoding="utf-8")
            result = self.run_cli(source, "safe", "--response-file", str(bad))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((article / "index.md").read_bytes(), before)
            self.assertEqual((article / "review-report.md").read_bytes(), old_report)
            self.assertFalse(any(article.glob(".review-report-*.tmp")))

    def test_source_change_during_supplier_stops_without_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            source = Path(temp_name)
            article = write_article(source, "race")
            index = article / "index.md"

            def supplier(_request: dict[str, object]) -> object:
                index.write_bytes(index.read_bytes() + "追記".encode("utf-8"))
                return review_article.fake_response()

            with self.assertRaises(review_article.ReviewError):
                review_article.create_review("race", article, index, supplier, "test", False)
            self.assertFalse((article / "review-report.md").exists())

    def test_secret_input_stops_without_printing_value(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            source = Path(temp_name)
            secret = "gh" + "p_" + "abcdefghijklmnopqrstuvwxyz123456"
            write_article(source, "secret", body=f"確認用 {secret}")
            result = self.run_cli(source, "secret", "--dry-run")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("GitHub token", result.stderr)
            self.assertNotIn(secret, result.stdout + result.stderr)
            self.assertFalse((source / "secret" / "review-report.md").exists())

    def test_secret_and_dangerous_ai_output_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            source = Path(temp_name)
            article = write_article(source, "output")
            response = response_with_finding()
            response["user_checklist"] = ["<script>alert(1)</script>"]
            path = source / "response.json"
            path.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
            result = self.run_cli(source, "output", "--response-file", str(path))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("危険なHTML", result.stderr)
            self.assertFalse((article / "review-report.md").exists())

    def test_secret_ai_output_stops_without_printing_value(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            source = Path(temp_name)
            article = write_article(source, "output-secret")
            secret = "gh" + "p_" + "abcdefghijklmnopqrstuvwxyz123456"
            response = response_with_finding()
            response["user_checklist"] = [f"確認 {secret}"]
            path = source / "response.json"
            path.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
            result = self.run_cli(source, "output-secret", "--response-file", str(path))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("GitHub token", result.stderr)
            self.assertNotIn(secret, result.stdout + result.stderr)
            self.assertFalse((article / "review-report.md").exists())

    def test_request_contains_image_names_but_not_image_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            source = Path(temp_name)
            article = write_article(source, "image", body="![画面](images/01.png)")
            images = article / "images"
            images.mkdir()
            binary = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
            (images / "01.png").write_bytes(binary)
            result = self.run_cli(source, "image", "--print-request")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            request = json.loads(result.stdout)
            self.assertEqual(request["image_references"], [{"filename": "images/01.png", "alt": "画面"}])
            self.assertNotIn(base64.b64encode(binary).decode("ascii"), result.stdout)

    def test_stale_report_is_warning_not_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            source = Path(temp_name)
            article = write_article(source, "stale")
            self.assertEqual(self.run_cli(source, "stale", "--fake").returncode, 0)
            (article / "index.md").write_bytes((article / "index.md").read_bytes() + "更新".encode("utf-8"))
            result = self.run_cli(source, "stale", "--status")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("古い結果", result.stdout)

    def test_malformed_existing_report_stops_status_check(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            source = Path(temp_name)
            article = write_article(source, "malformed")
            (article / "review-report.md").write_text(
                "---\nreview_schema: 1\narticle: malformed\narticle_hash: \"sha256:" + "0" * 64 + "\"\n---\n\n分類なし\n",
                encoding="utf-8",
            )
            result = self.run_cli(source, "malformed", "--status")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("実行情報", result.stderr)

    def test_same_input_reuses_report_without_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            source = Path(temp_name)
            article = write_article(source, "repeat")
            self.assertEqual(self.run_cli(source, "repeat", "--fake").returncode, 0)
            first = (article / "review-report.md").read_bytes()
            result = self.run_cli(source, "repeat", "--fake")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("再利用", result.stdout)
            self.assertEqual((article / "review-report.md").read_bytes(), first)

    def test_gemini_requires_environment_key_without_leaking(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(review_article.ReviewError) as caught:
                review_article.call_gemini({"body": "テスト"})
        self.assertIn("GEMINI_API_KEY", str(caught.exception))

    def test_gemini_uses_pinned_model_structured_output_and_no_tools(self) -> None:
        recorded: dict[str, object] = {}

        class FakeInteractions:
            def create(self, **kwargs: object) -> object:
                recorded.update(kwargs)
                return type(
                    "Interaction",
                    (),
                    {"output_text": json.dumps(review_article.fake_response(), ensure_ascii=False)},
                )()

        class FakeClient:
            def __init__(self, api_key: str) -> None:
                recorded["api_key_received"] = bool(api_key)
                self.interactions = FakeInteractions()

            def close(self) -> None:
                recorded["closed"] = True

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-only-key"}, clear=True):
            response = review_article.call_gemini(
                {"body": "日本語本文", "image_references": [{"filename": "images/01.png", "alt": "画面"}]},
                client_factory=FakeClient,
            )
        self.assertEqual(response, review_article.fake_response())
        self.assertEqual(recorded["model"], "gemini-3.6-flash")
        self.assertFalse(recorded["store"])
        self.assertNotIn("tools", recorded)
        self.assertEqual(recorded["response_format"]["mime_type"], "application/json")
        self.assertTrue(recorded["api_key_received"])
        self.assertTrue(recorded["closed"])

    def test_gemini_failure_does_not_create_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            source = Path(temp_name)
            article = write_article(source, "gemini-failure")
            index = article / "index.md"
            before = index.read_bytes()

            def supplier(_request: dict[str, object]) -> object:
                raise review_article.ReviewError("通信失敗")

            with self.assertRaises(review_article.ReviewError):
                review_article.create_review("gemini-failure", article, index, supplier, "Gemini test", False)
            self.assertEqual(index.read_bytes(), before)
            self.assertFalse((article / "review-report.md").exists())

    def test_report_remains_excluded_from_sync(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            source = root / "source"
            output = root / "output"
            write_article(source, "excluded")
            self.assertEqual(self.run_cli(source, "excluded", "--fake").returncode, 0)
            result = subprocess.run(
                [sys.executable, str(SYNC_SCRIPT), "--source", str(source), "--output", str(output)],
                capture_output=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(any(output.rglob("review-report.md")))

    def test_shortcut_contract_is_unchanged(self) -> None:
        config = (PROJECT_ROOT / "scripts" / "configure_obsidian_shortcuts.ps1").read_text(encoding="utf-8")
        preview = (PROJECT_ROOT / "preview.ps1").read_text(encoding="utf-8")
        publish = (PROJECT_ROOT / "publish.ps1").read_text(encoding="utf-8")
        self.assertIn('key = "V"', config)
        self.assertIn('key = "R"', config)
        self.assertIn('key = "P"', config)
        self.assertIn('key = "L"', config)
        self.assertNotIn('key = "C"', config)
        self.assertIn("hugo server", preview)
        self.assertIn("if (-not $Approve)", publish)
        launcher = (PROJECT_ROOT / "launch-review.ps1").read_text(encoding="utf-8")
        self.assertIn("MessageBox", launcher)
        self.assertIn('& $reviewScript -SourceFile $SourceFile -Gemini -Replace', launcher)
        self.assertIn('[switch]$Interactive', launcher)
        self.assertIn('Start-Process powershell', launcher)


if __name__ == "__main__":
    unittest.main()

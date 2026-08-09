from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import weekly_research_notify as notify


SUMMARY = {"content": "【週次リサーチ】2026-W33\nPDFを確認してください。", "allowed_mentions": {"parse": [], "users": [], "roles": [], "replied_user": False}}
WEBHOOK = "https://discord.com/api/webhooks/123456789/test-token"


class NotifyTests(unittest.TestCase):
    def pdf(self, folder: str) -> Path:
        path = Path(folder) / "report.pdf"; path.write_bytes(b"%PDF-1.4\n%%EOF")
        return path

    def test_multipart_contains_summary_and_pdf_without_webhook(self):
        with tempfile.TemporaryDirectory() as folder:
            body, content_type = notify.multipart_body(SUMMARY, self.pdf(folder), "fixed")
        self.assertIn(b"payload_json", body)
        self.assertIn(b"weekly-research.pdf", body)
        self.assertIn(b"%PDF", body)
        self.assertNotIn(WEBHOOK.encode(), body)
        self.assertEqual(content_type, "multipart/form-data; boundary=fixed")

    def test_mentions_must_be_disabled(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "summary.json"
            path.write_text(json.dumps({"content": "test", "allowed_mentions": {"parse": ["everyone"]}}), encoding="utf-8")
            with self.assertRaisesRegex(notify.NotifyError, "メンション"):
                notify.load_summary(path)

    def test_success_and_limited_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            calls = []
            statuses = iter([429, 503, 204])
            def transport(url, body, content_type, timeout):
                calls.append((url, content_type, timeout)); return notify.HttpResult(next(statuses))
            sleeps = []
            attempts = notify.send(WEBHOOK, SUMMARY, self.pdf(folder), transport, sleeps.append)
        self.assertEqual(attempts, 3)
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [1.0, 2.0])

    def test_timeout_is_not_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            calls = []
            def transport(*args): calls.append(1); raise TimeoutError()
            with self.assertRaisesRegex(notify.NotifyError, "再試行しません"):
                notify.send(WEBHOOK, SUMMARY, self.pdf(folder), transport)
        self.assertEqual(calls, [1])

    def test_other_4xx_is_not_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(notify.NotifyError, "HTTP 401"):
                notify.send(WEBHOOK, SUMMARY, self.pdf(folder), lambda *args: notify.HttpResult(401))

    def test_rejects_non_discord_url_and_non_pdf(self):
        with self.assertRaisesRegex(notify.NotifyError, "接続先"):
            notify.validate_webhook("https://example.com/api/webhooks/1/x")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.pdf"; path.write_bytes(b"not pdf")
            with self.assertRaisesRegex(notify.NotifyError, "PDF"):
                notify.multipart_body(SUMMARY, path)

    def test_connection_test_uses_fixed_message(self):
        with tempfile.TemporaryDirectory() as folder:
            pdf = self.pdf(folder)
            missing_summary = Path(folder) / "missing.json"
            captured = []
            with patch.dict(os.environ, {notify.SECRET_NAME: WEBHOOK}), patch.object(
                notify, "send", side_effect=lambda webhook, summary, path: captured.append((webhook, summary, path)) or 1
            ):
                result = notify.main(["--summary", str(missing_summary), "--pdf", str(pdf), "--connection-test"])
        self.assertEqual(result, 0)
        self.assertEqual(captured[0][1], notify.CONNECTION_TEST_SUMMARY)


if __name__ == "__main__":
    unittest.main()

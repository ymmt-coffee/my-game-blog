import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import discord_notify


class DiscordNotifyTests(unittest.TestCase):
    def test_publish_push_is_classified_only_for_matching_article(self):
        result = discord_notify.classify_deployment(
            "push", "publish: sample-game\n", ["content/posts/sample-game/index.md", "content/posts/sample-game/images/01.png"]
        )
        self.assertEqual(result, discord_notify.Classification("publish", slug="sample-game"))

    def test_normal_commit_has_no_publish_notification(self):
        result = discord_notify.classify_deployment("push", "docs: update", ["docs/README.md"])
        self.assertEqual(result.kind, "none")

    def test_schedule_and_workflow_dispatch_never_publish(self):
        for event in ("schedule", "workflow_dispatch"):
            with self.subTest(event=event):
                result = discord_notify.classify_deployment(event, "publish: sample-game", ["content/posts/sample-game/index.md"])
                self.assertEqual(result.kind, "none")

    def test_invalid_or_mismatched_publish_slug_requires_attention(self):
        cases = [
            ("publish: ../secret", ["content/posts/secret/index.md"]),
            ("publish: ", ["content/posts/sample-game/index.md"]),
            ("publish: sample-game", ["docs/README.md"]),
            ("publish: sample-game", ["content/posts/other/index.md"]),
        ]
        for message, paths in cases:
            with self.subTest(message=message, paths=paths):
                self.assertEqual(discord_notify.classify_deployment("push", message, paths).kind, "attention")

    def test_payload_disables_mentions_and_contains_no_supplied_secret(self):
        payload = discord_notify.build_payload(
            "publish",
            repository="owner/repo",
            sha="abcdef0123456789",
            event_name="push",
            run_url="https://github.example/actions/1",
            article_url="https://pages.example/posts/sample-game/",
            slug="sample-game",
        )
        self.assertEqual(payload["allowed_mentions"]["parse"], [])
        self.assertNotIn("@everyone", json.dumps(payload, ensure_ascii=False))
        self.assertNotIn("WEBHOOK", json.dumps(payload, ensure_ascii=False))

    def test_success_build_deploy_verify_and_error_payloads_are_distinct(self):
        publish = discord_notify.build_payload(
            "publish", repository="o/r", sha="a", event_name="push", run_url="run", article_url="page", slug="slug"
        )
        for stage in ("build", "deploy", "公開URL確認"):
            error = discord_notify.build_payload(
                "error", repository="o/r", sha="a", event_name="push", run_url="run", stage=stage
            )
            self.assertIn(stage, error["content"])
            self.assertNotEqual(publish["content"], error["content"])

    def test_live_smoke_payload_is_clearly_marked_as_test(self):
        for kind, channel in (("publish", "公開通知"), ("error", "エラー通知"), ("attention", "要確認")):
            with self.subTest(kind=kind):
                payload = discord_notify.build_payload(
                    kind, repository="o/r", sha="a", event_name="workflow_dispatch", run_url="run", test_message=True
                )
                self.assertIn("【接続テスト】", payload["content"])
                self.assertIn(channel, payload["content"])
                self.assertIn("実際の公開・失敗・要確認は発生していません", payload["content"])

    def test_429_and_5xx_retry_only_up_to_three_attempts(self):
        for statuses in ([429, 204], [503, 599, 204], [503, 503, 503]):
            calls = []

            def fake_transport(_url, _body, _timeout):
                status = statuses[len(calls)]
                calls.append(status)
                return discord_notify.HttpResult(status, {"Retry-After": "0"})

            with self.subTest(statuses=statuses):
                if statuses[-1] == 204:
                    discord_notify.send_notification(
                        "test-webhook", {"content": "test"}, transport=fake_transport, sleeper=lambda _: None, validate_url=False
                    )
                else:
                    with self.assertRaises(discord_notify.NotificationError):
                        discord_notify.send_notification(
                            "test-webhook", {"content": "test"}, transport=fake_transport, sleeper=lambda _: None, validate_url=False
                        )
                self.assertEqual(len(calls), len(statuses))
                self.assertLessEqual(len(calls), 3)

    def test_400_401_403_are_not_retried(self):
        for status in (400, 401, 403):
            calls = []

            def fake_transport(_url, _body, _timeout):
                calls.append(status)
                return discord_notify.HttpResult(status, {})

            with self.subTest(status=status):
                with self.assertRaises(discord_notify.NotificationError):
                    discord_notify.send_notification(
                        "test-webhook", {"content": "test"}, transport=fake_transport, sleeper=lambda _: None, validate_url=False
                    )
                self.assertEqual(calls, [status])

    def test_connection_uncertainty_is_not_retried_or_mutating(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary, "article.md")
            marker.write_text("unchanged", encoding="utf-8")
            calls = []

            def failed_transport(_url, _body, _timeout):
                calls.append(1)
                raise discord_notify.NotificationError("unknown result")

            with patch("discord_notify.subprocess.run") as git_process:
                with self.assertRaises(discord_notify.NotificationError):
                    discord_notify.send_notification(
                        "test-webhook", {"content": "test"}, transport=failed_transport, sleeper=lambda _: None, validate_url=False
                    )
                git_process.assert_not_called()
            self.assertEqual(marker.read_text(encoding="utf-8"), "unchanged")
            self.assertEqual(calls, [1])

    def test_missing_secret_reports_name_without_value(self):
        parser = discord_notify.build_parser()
        args = parser.parse_args(
            [
                "send", "--kind", "publish", "--repository", "o/r", "--sha", "abc", "--event", "push", "--run-url", "run"
            ]
        )
        with patch.dict("discord_notify.os.environ", {}, clear=True):
            with self.assertRaises(discord_notify.NotificationError) as caught:
                discord_notify._run_send(args)
        self.assertIn("DISCORD_WEBHOOK_PUBLISH", str(caught.exception))
        self.assertNotIn("https://", str(caught.exception))

    def test_pages_verification_checks_article_after_base(self):
        calls = []

        def opener(url, _timeout):
            calls.append(url)
            return 200

        discord_notify.verify_pages(["https://pages.example/", "https://pages.example/posts/sample/"], opener=opener, sleeper=lambda _: None)
        self.assertEqual(len(calls), 2)

    def test_pages_verification_failure_is_reported_without_response_body(self):
        with self.assertRaisesRegex(discord_notify.NotificationError, "URL確認に失敗") as caught:
            discord_notify.verify_pages(
                ["https://pages.example/posts/sample/"], opener=lambda _url, _timeout: 503, attempts=2, sleeper=lambda _: None
            )
        self.assertNotIn("response body", str(caught.exception))

    def test_build_failure_is_selected_before_later_jobs(self):
        stage = discord_notify.determine_error_stage("failure", "skipped", "skipped", "skipped", "skipped")
        self.assertEqual(stage, "build")

    def test_workflow_uses_fakeable_script_and_never_calls_discord_in_tests(self):
        workflow = Path(__file__).parents[1] / ".github" / "workflows" / "hugo.yml"
        tests = Path(__file__)
        live_endpoint_marker = "discord" + ".com/api"
        self.assertNotIn(live_endpoint_marker, tests.read_text(encoding="utf-8"))
        workflow_text = workflow.read_text(encoding="utf-8")
        self.assertIn("needs: [build, deploy, verify]", workflow_text)
        self.assertIn("if: needs.build.outputs.notification_kind == 'publish'", workflow_text)
        self.assertIn("needs: [build, deploy, verify, notify_publish, notify_attention]", workflow_text)
        self.assertIn("needs.build.result == 'failure'", workflow_text)
        self.assertIn("discord_test:", workflow_text)
        self.assertIn("notify_connection_test:", workflow_text)
        self.assertEqual(workflow_text.count("--test-message"), 3)
        self.assertIn("inputs.discord_test == true", workflow_text)
        for secret_name in discord_notify.SECRET_NAMES.values():
            self.assertIn(secret_name, workflow_text)


if __name__ == "__main__":
    unittest.main()

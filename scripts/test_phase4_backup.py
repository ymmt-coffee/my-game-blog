import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path, PurePosixPath
from unittest.mock import patch

import phase4_backup as backup
import backup_error_notify


class Phase4BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.destination = self.root / "destination"
        self.source.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def records(self):
        return backup.inventory(self.source, rules=[(True, "**")])[0]

    def test_inventory_never_changes_source(self):
        item = self.source / "note.txt"
        item.write_text("original", encoding="utf-8")
        before = (item.read_bytes(), item.stat().st_mtime_ns)
        rows, summary = backup.inventory(self.source, rules=[(True, "**")])
        self.assertEqual((item.read_bytes(), item.stat().st_mtime_ns), before)
        self.assertEqual((len(rows), summary.files), (1, 1))

    def test_daily_copy_adds_and_updates_without_deleting_destination_only_file(self):
        (self.source / "note.txt").write_text("new", encoding="utf-8")
        self.destination.mkdir()
        (self.destination / "note.txt").write_text("old", encoding="utf-8")
        (self.destination / "deleted-at-source.txt").write_text("keep", encoding="utf-8")
        backup.local_copy(self.source, self.destination, self.records(), "1" * 32)
        self.assertEqual((self.destination / "note.txt").read_text(encoding="utf-8"), "new")
        self.assertTrue((self.destination / "deleted-at-source.txt").exists())

    def test_required_exclusions(self):
        names = [".git", "public", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache", ".venv", "venv", "node_modules"]
        for name in names:
            folder = self.source / name
            folder.mkdir()
            (folder / "excluded.txt").write_text("x", encoding="utf-8")
        (self.source / "included.txt").write_text("ok", encoding="utf-8")
        rows, summary = backup.inventory(self.source)
        self.assertEqual([row.relative for row in rows], ["included.txt"])
        self.assertEqual(summary.excluded_files, len(names))
        git_file_root = self.source / "submodule"
        git_file_root.mkdir()
        (git_file_root / ".git").write_text("gitdir: external", encoding="utf-8")
        rows, _summary = backup.inventory(self.source)
        self.assertNotIn("submodule/.git", [row.relative for row in rows])

    def test_monthly_scope_includes_only_blog_essentials(self):
        included_paths = [
            ".obsidian/settings.json", "30_Projects/01_blog/article/index.md",
            "30_Projects/10_Apps/my-blog/config.toml", "30_Projects/10_Apps/my-game-blog/hugo.toml",
        ]
        for relative in included_paths + ["30_Projects/10_Apps/other-tool/source.py"]:
            path = self.source.joinpath(*PurePosixPath(relative).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("safe", encoding="utf-8")
        rows, _summary = backup.inventory(self.source, rules=backup._filter_rules(backup.MONTHLY_FILTER_PATH))
        self.assertEqual([row.relative for row in rows], sorted(included_paths))

    def test_reparse_point_is_not_followed(self):
        link = self.source / "simulated-junction"
        link.mkdir()
        (link / "private.txt").write_text("secret", encoding="utf-8")
        real = backup._is_reparse
        with patch("phase4_backup._is_reparse", side_effect=lambda path: path == link or real(path)):
            rows, summary = backup.inventory(self.source, rules=[(True, "**")])
        self.assertEqual(rows, [])
        self.assertEqual(summary.reparse_points, 1)

    def test_destination_inside_source_is_rejected(self):
        with self.assertRaises(backup.BackupError):
            backup.validate_destination(self.source / "backup", self.source)

    def test_path_traversal_record_is_rejected(self):
        row = backup.FileRecord("../outside.txt", 1, 1)
        with self.assertRaises(backup.BackupError):
            backup.local_copy(self.source, self.destination, [row], "2" * 32)

    def test_duplicate_run_lock_is_rejected_and_released(self):
        lock = self.root / "lock"
        with backup.RunLock(lock):
            with self.assertRaises(backup.BackupError):
                with backup.RunLock(lock):
                    pass
        self.assertFalse(lock.exists())

    def test_file_changed_during_copy_has_no_completed_or_temporary_file(self):
        item = self.source / "note.txt"
        item.write_text("before", encoding="utf-8")
        record = self.records()[0]
        real_hash = backup.sha256
        calls = 0

        def changing_hash(path):
            nonlocal calls
            calls += 1
            value = real_hash(path)
            if calls == 1:
                item.write_text("after", encoding="utf-8")
            return value

        with patch("phase4_backup.sha256", side_effect=changing_hash):
            with self.assertRaises(backup.BackupError):
                backup.local_copy(self.source, self.destination, [record], "3" * 32)
        self.assertFalse((self.destination / "note.txt").exists())
        self.assertEqual(list(self.destination.glob(".*phase4-part*")), [])

    def test_monthly_name_is_strict(self):
        self.assertEqual(backup.validate_snapshot_name("2026-08"), "2026-08")
        for value in ("2026-8", "../2026-08", "2026-13", "x2026-08"):
            with self.subTest(value=value), self.assertRaises(backup.BackupError):
                backup.validate_snapshot_name(value)

    def test_same_month_reuses_verified_snapshot(self):
        (self.source / "note.txt").write_text("data", encoding="utf-8")
        target, created = backup.create_monthly_snapshot(self.source, self.destination, self.records(), "2026-08")
        target2, created2 = backup.create_monthly_snapshot(self.source, self.destination, self.records(), "2026-08")
        self.assertTrue(created)
        self.assertFalse(created2)
        self.assertEqual(target, target2)

    def test_monthly_failure_leaves_no_success_marker(self):
        (self.source / "note.txt").write_text("data", encoding="utf-8")
        with patch("phase4_backup.verify_local", side_effect=backup.BackupError("verification", "failed")):
            with self.assertRaises(backup.BackupError):
                backup.create_monthly_snapshot(self.source, self.destination, self.records(), "2026-08")
        self.assertFalse((self.destination / "2026-08" / ".phase4-complete.json").exists())

    def test_retention_selects_only_thirteenth_and_older(self):
        names = [f"2025-{month:02d}" for month in range(1, 13)] + ["2026-01"]
        self.assertEqual(backup.retention_candidates(names), ["2025-01"])

    def test_retention_never_deletes_when_unsafe_or_unverified(self):
        twelve = [f"2025-{month:02d}" for month in range(1, 13)]
        self.assertEqual(backup.retention_candidates(twelve), [])
        self.assertEqual(backup.retention_candidates(twelve + ["invalid"]), [])
        self.assertEqual(backup.retention_candidates(twelve + ["2026-01"], latest_verified=False), [])

    def test_capacity_shortage_is_detected_before_copy(self):
        self.assertFalse(backup.capacity_is_sufficient(100, 1000, 50, 100, 20))
        self.assertTrue(backup.capacity_is_sufficient(500, 1000, 50, 100, 20))

    def test_capacity_auth_network_and_api_errors_are_safe_categories(self):
        for kind in ("capacity", "authentication", "network", "drive_api"):
            request = backup.safe_notification_request(kind, "a" * 32, "2026-08-02T12:34:56+09:00")
            self.assertEqual(request["failure_kind"], kind)
        with self.assertRaises(backup.BackupError):
            backup.parse_rclone_about("token=private")

    def test_notification_rejects_file_names_and_free_text(self):
        with self.assertRaises(backup.BackupError):
            backup.safe_notification_request("network: personal-note.md", "a" * 32, "2026-08-02T12:34:56+09:00")

    def test_discord_notification_is_stubbed_and_contains_no_personal_file_name(self):
        environment = {
            "FAILURE_KIND": "network", "BACKUP_RUN_ID": "c" * 32,
            "OCCURRED_AT": "2026-08-02T12:34:56+09:00", "DISCORD_WEBHOOK_ERROR": "not-sent",
            "ACTIONS_RUN_URL": "https://github.example/actions/1",
        }
        with patch.dict(os.environ, environment, clear=True), patch("sys.argv", ["backup_error_notify.py", "send"]), patch(
            "backup_error_notify.send_notification"
        ) as send:
            self.assertEqual(backup_error_notify.main(), 0)
            payload = send.call_args.args[1]
            self.assertNotIn("personal-note.md", json.dumps(payload))
            self.assertNotIn("not-sent", json.dumps(payload))

    def test_state_contains_only_summary_not_file_names_or_secrets(self):
        state = self.root / "state.json"
        backup.write_state(state, "failure", "network", "b" * 32, backup.Summary(2, 20))
        text = state.read_text(encoding="utf-8")
        self.assertNotIn("note.txt", text)
        self.assertNotIn("token", text.lower())
        self.assertEqual(json.loads(text)["files"], 2)

    def test_restore_to_source_is_rejected(self):
        item = self.root / "backup.txt"
        item.write_text("fictional", encoding="utf-8")
        with self.assertRaises(backup.BackupError):
            backup.restore_file(item, self.source, self.source, backup.sha256(item))

    def test_fictional_file_restore_hash_matches(self):
        item = self.root / "backup.txt"
        item.write_text("fictional phase 4 restore test", encoding="utf-8")
        restored = backup.restore_file(item, self.root / "restore", self.source, backup.sha256(item))
        self.assertEqual(backup.sha256(restored), backup.sha256(item))

    def test_restore_failure_does_not_touch_source(self):
        original = self.source / "original.txt"
        original.write_text("unchanged", encoding="utf-8")
        backup_file = self.root / "bad.txt"
        backup_file.write_text("bad", encoding="utf-8")
        with self.assertRaises(backup.BackupError):
            backup.restore_file(backup_file, self.root / "restore", self.source, "0" * 64)
        self.assertEqual(original.read_text(encoding="utf-8"), "unchanged")

    def test_rclone_plan_is_copy_not_sync_and_skips_links(self):
        command = backup.rclone_copy_command(self.source, "drive:backup/daily", dry_run=True)
        self.assertEqual(command[1], "copy")
        self.assertNotIn("sync", command)
        self.assertIn("--skip-links", command)
        self.assertIn("--dry-run", command)

    def test_rclone_destination_traversal_is_rejected(self):
        with self.assertRaises(backup.BackupError):
            backup.rclone_copy_command(self.source, "drive:backup/../private")

    def test_task_xml_has_required_safety_settings(self):
        xml = backup.task_xml(Path("C:/safe/run.ps1"), Path("C:/safe"), "drive:backup", "Daily")
        self.assertIn("<StartWhenAvailable>true</StartWhenAvailable>", xml)
        self.assertIn("<WakeToRun>true</WakeToRun>", xml)
        self.assertIn("<DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries>", xml)
        self.assertIn("<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>", xml)
        self.assertIn("<Count>2</Count>", xml)
        self.assertIn("<LogonType>InteractiveToken</LogonType>", xml)
        self.assertIn("-Mode Daily", xml)

    def test_monthly_task_runs_only_on_day_one(self):
        xml = backup.task_xml(Path("C:/safe/run.ps1"), Path("C:/safe"), "drive:backup", "Monthly")
        self.assertIn("<ScheduleByMonth>", xml)
        self.assertIn("<Day>1</Day>", xml)
        self.assertIn("-Mode Monthly", xml)

    def test_windows_protection_and_tasks_are_safe_by_default(self):
        runner = (backup.PROJECT_ROOT / "scripts" / "run_phase4_backup.ps1").read_text(encoding="utf-8")
        protector = (backup.PROJECT_ROOT / "scripts" / "protect_rclone_config.ps1").read_text(encoding="utf-8")
        register = (backup.PROJECT_ROOT / "scripts" / "register_phase4_tasks.ps1").read_text(encoding="utf-8")
        self.assertIn("--password-command", runner)
        self.assertIn('Invoke-Rclone @("size", $Source', runner)
        self.assertIn("$MonthlySize.count", runner)
        self.assertIn("$MonthlySize.bytes", runner)
        self.assertIn("[switch]$Reconcile", runner)
        self.assertIn("-not $Reconcile", runner)
        self.assertIn("ProtectedData]::Protect", protector)
        self.assertIn("DataProtectionScope]::CurrentUser", protector)
        self.assertNotIn("ConvertFrom-SecureString", protector)
        self.assertIn("icacls.exe", protector)
        self.assertIn("/inheritance:r", protector)
        self.assertIn("/grant:r", protector)
        self.assertIn("$Definition.Settings.Enabled = $false", register)
        self.assertIn("FullBackupStarted = $false", register)


if __name__ == "__main__":
    unittest.main()

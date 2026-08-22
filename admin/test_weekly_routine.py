from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from admin import weekly_routine


class WeeklyRoutineTests(unittest.TestCase):
    def test_week_starts_on_monday(self) -> None:
        self.assertEqual(weekly_routine.week_start(date(2026, 8, 23)), date(2026, 8, 17))

    def test_completed_collection_is_not_repeated(self) -> None:
        action = weekly_routine.collection_action(
            {"status": "partial"}, ready=True,
            now=datetime(2026, 8, 22, tzinfo=timezone.utc),
        )
        self.assertEqual((action.state, action.label, action.enabled), ("done", "更新済み", False))

    def test_failed_collection_has_six_hour_cooldown(self) -> None:
        failed_at = datetime(2026, 8, 22, 10, tzinfo=timezone.utc)
        action = weekly_routine.collection_action(
            {"status": "failure", "completed_at": failed_at.isoformat()}, ready=True,
            now=failed_at + timedelta(hours=1),
        )
        self.assertEqual(action.state, "cooldown")
        self.assertFalse(action.enabled)

    def test_collection_waits_until_thursday(self) -> None:
        now = datetime(2026, 8, 19, 12, tzinfo=timezone.utc)
        action = weekly_routine.collection_action(
            None, ready=True, now=now, due_at=now + timedelta(hours=1),
        )
        self.assertEqual(action.state, "not_due")


if __name__ == "__main__":
    unittest.main()

import sqlite3
import tempfile
import unittest
from pathlib import Path

import sqlite_snapshot


class SqliteSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "live" / "admin.sqlite3"
        self.snapshot = self.root / "backup-source" / "admin.sqlite3"
        self.source.parent.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def create_source(self, value: str = "saved") -> None:
        connection = sqlite3.connect(self.source)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample VALUES (?)", (value,))
        connection.commit()
        connection.close()

    def read_value(self, path: Path) -> str:
        connection = sqlite3.connect(path)
        try:
            return str(connection.execute("SELECT value FROM sample").fetchone()[0])
        finally:
            connection.close()

    def test_snapshot_is_consistent_and_contains_committed_wal_data(self):
        self.create_source()
        self.assertEqual(sqlite_snapshot.create_snapshot(self.source, self.snapshot), "created")
        sqlite_snapshot.verify_database(self.snapshot)
        self.assertEqual(self.read_value(self.snapshot), "saved")

    def test_corrupt_source_does_not_replace_previous_good_snapshot(self):
        self.create_source("previous")
        sqlite_snapshot.create_snapshot(self.source, self.snapshot)
        before = self.snapshot.read_bytes()
        self.source.write_bytes(b"not sqlite")
        with self.assertRaises(sqlite_snapshot.SnapshotError):
            sqlite_snapshot.create_snapshot(self.source, self.snapshot)
        self.assertEqual(self.snapshot.read_bytes(), before)

    def test_missing_source_skips_only_when_no_stale_snapshot_exists(self):
        self.assertEqual(sqlite_snapshot.create_snapshot(self.source, self.snapshot), "skipped")
        self.snapshot.parent.mkdir(parents=True)
        self.snapshot.write_bytes(b"old")
        with self.assertRaises(sqlite_snapshot.SnapshotError):
            sqlite_snapshot.create_snapshot(self.source, self.snapshot)

    def test_restore_is_verified_and_only_writes_to_staging(self):
        self.create_source("restored")
        sqlite_snapshot.create_snapshot(self.source, self.snapshot)
        destination = self.root / "restore-staging" / "admin.sqlite3"
        sqlite_snapshot.restore_to_staging(self.snapshot, destination, self.source)
        self.assertEqual(self.read_value(destination), "restored")

    def test_restore_to_live_directory_is_rejected(self):
        self.create_source()
        sqlite_snapshot.create_snapshot(self.source, self.snapshot)
        with self.assertRaises(sqlite_snapshot.SnapshotError):
            sqlite_snapshot.restore_to_staging(self.snapshot, self.source, self.source)
        with self.assertRaises(sqlite_snapshot.SnapshotError):
            sqlite_snapshot.restore_to_staging(
                self.snapshot, self.source.parent / "replacement.sqlite3", self.source
            )


if __name__ == "__main__":
    unittest.main()

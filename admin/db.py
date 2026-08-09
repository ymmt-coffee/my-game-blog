"""管理画面のローカル状態DB。記事本文や秘密情報は保存しない。"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "var" / "admin" / "admin.sqlite3"

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('success', 'warning', 'failure')),
    message_code TEXT NOT NULL,
    safe_message TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=5)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection
    except Exception:
        connection.close()
        raise


def initialize(db_path: Path = DEFAULT_DB_PATH) -> None:
    with closing(connect(db_path)) as connection:
        integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError("管理画面の状態DBに異常があります。自動修復せず停止しました。")
        connection.executescript(SCHEMA_V1)
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (1, utc_now()),
        )
        connection.commit()


def record_event(
    event_type: str,
    result: str,
    message_code: str,
    safe_message: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    if result not in {"success", "warning", "failure"}:
        raise ValueError("許可されていない処理結果です。")
    with closing(connect(db_path)) as connection:
        connection.execute(
            """INSERT INTO app_events
               (event_type, result, message_code, safe_message, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (event_type, result, message_code, safe_message, utc_now()),
        )
        connection.commit()


def recent_events(db_path: Path = DEFAULT_DB_PATH, limit: int = 50) -> list[dict[str, object]]:
    safe_limit = min(max(limit, 1), 100)
    with closing(connect(db_path)) as connection:
        rows = connection.execute(
            """SELECT event_type, result, message_code, safe_message, created_at
               FROM app_events ORDER BY id DESC LIMIT ?""",
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]

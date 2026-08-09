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

SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS articles (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE COLLATE NOCASE,
    article_type TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN
        ('draft','review_pending','ready','scheduled','published','archived')),
    previous_state TEXT,
    source_path TEXT NOT NULL UNIQUE,
    file_hash TEXT NOT NULL,
    last_saved_at TEXT NOT NULL,
    scheduled_at TEXT,
    published_at TEXT,
    last_reviewed_at TEXT,
    reviewed_file_hash TEXT,
    archived_at TEXT,
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS article_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id TEXT NOT NULL REFERENCES articles(id),
    event_type TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT,
    result TEXT NOT NULL CHECK (result IN ('success','warning','failure')),
    file_hash TEXT,
    message_code TEXT,
    safe_message TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS article_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id TEXT NOT NULL REFERENCES articles(id),
    severity TEXT NOT NULL CHECK (severity IN ('info','warning','error')),
    code TEXT NOT NULL,
    safe_message TEXT NOT NULL,
    resolved_at TEXT,
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
        connection.executescript(SCHEMA_V2)
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (2, utc_now()),
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


def create_article(
    article_id: str,
    slug: str,
    article_type: str,
    source_path: str,
    file_hash: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    now = utc_now()
    with closing(connect(db_path)) as connection:
        connection.execute(
            """INSERT INTO articles
               (id, slug, article_type, state, source_path, file_hash,
                last_saved_at, revision, created_at, updated_at)
               VALUES (?, ?, ?, 'draft', ?, ?, ?, 1, ?, ?)""",
            (article_id, slug, article_type, source_path, file_hash, now, now, now),
        )
        connection.execute(
            """INSERT INTO article_events
               (article_id, event_type, to_state, result, file_hash, message_code, safe_message, created_at)
               VALUES (?, 'create', 'draft', 'success', ?, 'article_created', '記事を作成しました。', ?)""",
            (article_id, file_hash, now),
        )
        connection.commit()


def register_scanned_article(
    article_id: str,
    slug: str,
    article_type: str,
    source_path: str,
    file_hash: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    now = utc_now()
    with closing(connect(db_path)) as connection:
        connection.execute(
            """INSERT OR IGNORE INTO articles
               (id, slug, article_type, state, source_path, file_hash,
                last_saved_at, revision, created_at, updated_at)
               VALUES (?, ?, ?, 'draft', ?, ?, ?, 1, ?, ?)""",
            (article_id, slug, article_type, source_path, file_hash, now, now, now),
        )
        connection.commit()


def get_article(article_id: str, db_path: Path = DEFAULT_DB_PATH) -> dict[str, object] | None:
    with closing(connect(db_path)) as connection:
        row = connection.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
    return dict(row) if row else None


def get_article_by_slug(slug: str, db_path: Path = DEFAULT_DB_PATH) -> dict[str, object] | None:
    with closing(connect(db_path)) as connection:
        row = connection.execute("SELECT * FROM articles WHERE slug = ? COLLATE NOCASE", (slug,)).fetchone()
    return dict(row) if row else None


def list_articles(db_path: Path = DEFAULT_DB_PATH, include_archived: bool = False) -> list[dict[str, object]]:
    where = "" if include_archived else "WHERE state != 'archived'"
    with closing(connect(db_path)) as connection:
        rows = connection.execute(
            f"SELECT * FROM articles {where} ORDER BY updated_at DESC, slug COLLATE NOCASE"
        ).fetchall()
    return [dict(row) for row in rows]


def update_saved_article(
    article_id: str,
    article_type: str,
    old_hash: str,
    new_hash: str,
    expected_revision: int,
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    now = utc_now()
    with closing(connect(db_path)) as connection:
        cursor = connection.execute(
            """UPDATE articles SET article_type = ?, state = 'draft', previous_state = NULL,
               file_hash = ?, last_saved_at = ?, revision = revision + 1, updated_at = ?,
               reviewed_file_hash = NULL
               WHERE id = ? AND revision = ? AND file_hash = ?""",
            (article_type, new_hash, now, now, article_id, expected_revision, old_hash),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            raise RuntimeError("記事台帳が別の操作で変更されました。")
        new_revision = expected_revision + 1
        connection.execute(
            """INSERT INTO article_events
               (article_id, event_type, to_state, result, file_hash, message_code, safe_message, created_at)
               VALUES (?, 'save', 'draft', 'success', ?, 'article_saved', '記事を保存しました。', ?)""",
            (article_id, new_hash, now),
        )
        connection.commit()
    return new_revision


def accept_external_change(
    article_id: str,
    new_hash: str,
    expected_revision: int,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    now = utc_now()
    with closing(connect(db_path)) as connection:
        cursor = connection.execute(
            """UPDATE articles SET state = 'draft', previous_state = NULL, file_hash = ?,
               revision = revision + 1, updated_at = ?, reviewed_file_hash = NULL
               WHERE id = ? AND revision = ?""",
            (new_hash, now, article_id, expected_revision),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            raise RuntimeError("記事台帳が別の操作で変更されました。")
        connection.execute(
            """INSERT INTO article_events
               (article_id, event_type, to_state, result, file_hash, message_code, safe_message, created_at)
               VALUES (?, 'external_change', 'draft', 'success', ?, 'external_change_accepted', '外部変更を確認して取り込みました。', ?)""",
            (article_id, new_hash, now),
        )
        connection.commit()


def set_archive(article_id: str, archived: bool, db_path: Path = DEFAULT_DB_PATH) -> None:
    now = utc_now()
    with closing(connect(db_path)) as connection:
        row = connection.execute("SELECT state FROM articles WHERE id = ?", (article_id,)).fetchone()
        if row is None:
            raise RuntimeError("記事が見つかりません。")
        old_state = str(row[0])
        if archived:
            if old_state == "archived":
                return
            new_state, previous_state, archived_at = "archived", old_state, now
            code, message = "article_archived", "記事をアーカイブしました。"
        else:
            if old_state != "archived":
                return
            previous = connection.execute("SELECT previous_state FROM articles WHERE id = ?", (article_id,)).fetchone()[0]
            new_state = previous if previous in {"draft", "review_pending", "ready", "published"} else "draft"
            previous_state, archived_at = None, None
            code, message = "article_restored", "記事をアーカイブから戻しました。"
        connection.execute(
            "UPDATE articles SET state = ?, previous_state = ?, archived_at = ?, updated_at = ? WHERE id = ?",
            (new_state, previous_state, archived_at, now, article_id),
        )
        connection.execute(
            """INSERT INTO article_events
               (article_id, event_type, from_state, to_state, result, message_code, safe_message, created_at)
               VALUES (?, 'state_change', ?, ?, 'success', ?, ?, ?)""",
            (article_id, old_state, new_state, code, message, now),
        )
        connection.commit()


def record_article_event(
    article_id: str,
    event_type: str,
    result: str,
    code: str,
    message: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    with closing(connect(db_path)) as connection:
        connection.execute(
            """INSERT INTO article_events
               (article_id, event_type, result, message_code, safe_message, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (article_id, event_type, result, code, message, utc_now()),
        )
        connection.commit()


def recent_article_events(article_id: str, db_path: Path = DEFAULT_DB_PATH, limit: int = 30) -> list[dict[str, object]]:
    with closing(connect(db_path)) as connection:
        rows = connection.execute(
            """SELECT event_type, from_state, to_state, result, safe_message, created_at
               FROM article_events WHERE article_id = ? ORDER BY id DESC LIMIT ?""",
            (article_id, min(max(limit, 1), 100)),
        ).fetchall()
    return [dict(row) for row in rows]

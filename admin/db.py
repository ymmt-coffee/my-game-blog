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

SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS publish_attempts (
    id TEXT PRIMARY KEY,
    article_id TEXT NOT NULL REFERENCES articles(id),
    file_hash TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('checked','running','success','failure','expired')),
    commit_sha TEXT,
    pages_url TEXT,
    safe_message TEXT,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
"""

SCHEMA_V4 = """
ALTER TABLE articles ADD COLUMN published_file_hash TEXT;
"""

SCHEMA_V5_COLUMNS = {
    "articles": {
        "scheduled_file_hash": "TEXT",
        "scheduled_claimed_at": "TEXT",
        "schedule_error": "TEXT",
    },
    "publish_attempts": {"scheduled_for": "TEXT"},
}

SCHEMA_V6 = """
CREATE TABLE IF NOT EXISTS analytics_daily (
    day TEXT NOT NULL,
    path TEXT NOT NULL,
    views INTEGER NOT NULL CHECK (views >= 0),
    visitors INTEGER NOT NULL CHECK (visitors >= 0),
    source TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    PRIMARY KEY (day, path, source)
);

CREATE TABLE IF NOT EXISTS analytics_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    filename TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    period_start TEXT,
    period_end TEXT,
    result TEXT NOT NULL CHECK (result IN ('success','failure')),
    safe_message TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

SCHEMA_V7 = """
CREATE TABLE IF NOT EXISTS social_drafts (
    id TEXT PRIMARY KEY,
    article_id TEXT NOT NULL REFERENCES articles(id),
    article_file_hash TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft','reviewed','posted')),
    platform TEXT,
    posted_url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    reviewed_at TEXT,
    posted_at TEXT
);
"""

SCHEMA_V8 = """
CREATE TABLE IF NOT EXISTS games (
    steam_app_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    developer TEXT,
    publisher TEXT,
    store_url TEXT NOT NULL,
    official_url TEXT,
    release_date TEXT,
    japan_availability TEXT NOT NULL CHECK (japan_availability IN ('unknown','available','unavailable')),
    japanese_support TEXT NOT NULL CHECK (japanese_support IN ('unknown','confirmed','planned','none')),
    single_player TEXT NOT NULL CHECK (single_player IN ('unknown','yes','no')),
    early_access INTEGER NOT NULL CHECK (early_access IN (0,1)),
    free_to_play INTEGER NOT NULL CHECK (free_to_play IN (0,1)),
    review_status TEXT,
    review_percent INTEGER CHECK (review_percent IS NULL OR review_percent BETWEEN 0 AND 100),
    review_count INTEGER CHECK (review_count IS NULL OR review_count >= 0),
    owned INTEGER NOT NULL DEFAULT 0 CHECK (owned IN (0,1)),
    wishlisted INTEGER NOT NULL DEFAULT 0 CHECK (wishlisted IN (0,1)),
    steam_synced_at TEXT,
    verified_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS game_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    steam_app_id TEXT NOT NULL REFERENCES games(steam_app_id),
    source_kind TEXT NOT NULL CHECK (source_kind IN ('rss','steam','official','manual')),
    source_name TEXT NOT NULL,
    article_title TEXT,
    url TEXT NOT NULL,
    published_at TEXT,
    summary TEXT,
    candidate_reason TEXT,
    discovered_at TEXT NOT NULL,
    UNIQUE (steam_app_id, url)
);

CREATE TABLE IF NOT EXISTS game_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    steam_app_id TEXT NOT NULL REFERENCES games(steam_app_id),
    currency TEXT NOT NULL,
    regular_price INTEGER CHECK (regular_price IS NULL OR regular_price >= 0),
    current_price INTEGER CHECK (current_price IS NULL OR current_price >= 0),
    discount_percent INTEGER CHECK (discount_percent IS NULL OR discount_percent BETWEEN 0 AND 100),
    sale_ends_at TEXT,
    source_url TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    UNIQUE (steam_app_id, observed_at)
);

CREATE TABLE IF NOT EXISTS game_candidates (
    id TEXT PRIMARY KEY,
    steam_app_id TEXT NOT NULL REFERENCES games(steam_app_id),
    cycle_key TEXT NOT NULL,
    candidate_kind TEXT NOT NULL CHECK (candidate_kind IN ('editorial','new_release','sale','free','manual')),
    status TEXT NOT NULL CHECK (status IN ('active','unconfirmed','excluded')),
    total_score INTEGER NOT NULL CHECK (total_score BETWEEN 0 AND 100),
    interest_score INTEGER NOT NULL CHECK (interest_score BETWEEN 0 AND 35),
    momentum_score INTEGER NOT NULL CHECK (momentum_score BETWEEN 0 AND 25),
    review_score INTEGER NOT NULL CHECK (review_score BETWEEN 0 AND 15),
    price_score INTEGER NOT NULL CHECK (price_score BETWEEN 0 AND 15),
    diversity_score INTEGER NOT NULL CHECK (diversity_score BETWEEN 0 AND 10),
    reasons_json TEXT NOT NULL,
    exclusion_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (steam_app_id, cycle_key, candidate_kind)
);

CREATE TABLE IF NOT EXISTS game_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    steam_app_id TEXT NOT NULL REFERENCES games(steam_app_id),
    decision TEXT NOT NULL CHECK (decision IN ('play_candidate','article_candidate','hold','not_interested')),
    note TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS game_collection_runs (
    id TEXT PRIMARY KEY,
    run_kind TEXT NOT NULL CHECK (run_kind IN ('trial','scheduled','manual','rss_only','steam_sync')),
    status TEXT NOT NULL CHECK (status IN ('running','success','partial','failure')),
    item_limit INTEGER NOT NULL CHECK (item_limit BETWEEN 1 AND 50),
    items_discovered INTEGER NOT NULL DEFAULT 0 CHECK (items_discovered >= 0),
    items_stored INTEGER NOT NULL DEFAULT 0 CHECK (items_stored >= 0),
    apify_items INTEGER NOT NULL DEFAULT 0 CHECK (apify_items >= 0),
    apify_cost_usd REAL NOT NULL DEFAULT 0 CHECK (apify_cost_usd >= 0),
    safe_message TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_game_sources_discovered ON game_sources(discovered_at);
CREATE INDEX IF NOT EXISTS idx_game_prices_observed ON game_prices(steam_app_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_game_candidates_cycle ON game_candidates(cycle_key, status, total_score DESC);
CREATE INDEX IF NOT EXISTS idx_game_decisions_game ON game_decisions(steam_app_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_game_runs_started ON game_collection_runs(started_at DESC);
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
        connection.executescript(SCHEMA_V3)
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (3, utc_now()),
        )
        migrated = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 4"
        ).fetchone()
        if migrated is None:
            connection.executescript(SCHEMA_V4)
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (4, utc_now()),
            )
        migrated = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 5"
        ).fetchone()
        if migrated is None:
            for table, columns in SCHEMA_V5_COLUMNS.items():
                existing = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
                for name, declaration in columns.items():
                    if name not in existing:
                        connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (5, utc_now()),
            )
        connection.executescript(SCHEMA_V6)
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (6, utc_now()),
        )
        connection.executescript(SCHEMA_V7)
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (7, utc_now()),
        )
        connection.executescript(SCHEMA_V8)
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (8, utc_now()),
        )
        connection.commit()


def save_game_observation(
    game: dict[str, object],
    source: dict[str, object] | None = None,
    price: dict[str, object] | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """検証済みゲーム情報と任意の出典・価格を一つのトランザクションで保存する。"""
    now = utc_now()
    with closing(connect(db_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """INSERT INTO games
               (steam_app_id,title,developer,publisher,store_url,official_url,release_date,
                japan_availability,japanese_support,single_player,early_access,free_to_play,
                review_status,review_percent,review_count,owned,wishlisted,steam_synced_at,
                verified_at,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(steam_app_id) DO UPDATE SET
                title=excluded.title,developer=excluded.developer,publisher=excluded.publisher,
                store_url=excluded.store_url,official_url=excluded.official_url,
                release_date=excluded.release_date,japan_availability=excluded.japan_availability,
                japanese_support=excluded.japanese_support,single_player=excluded.single_player,
                early_access=excluded.early_access,free_to_play=excluded.free_to_play,
                review_status=excluded.review_status,review_percent=excluded.review_percent,
                review_count=excluded.review_count,
                owned=CASE WHEN excluded.steam_synced_at IS NULL THEN games.owned ELSE excluded.owned END,
                wishlisted=CASE WHEN excluded.steam_synced_at IS NULL THEN games.wishlisted ELSE excluded.wishlisted END,
                steam_synced_at=excluded.steam_synced_at,verified_at=excluded.verified_at,
                updated_at=excluded.updated_at""",
            (
                game["steam_app_id"], game["title"], game.get("developer"), game.get("publisher"),
                game["store_url"], game.get("official_url"), game.get("release_date"),
                game["japan_availability"], game["japanese_support"], game["single_player"],
                int(bool(game.get("early_access"))), int(bool(game.get("free_to_play"))),
                game.get("review_status"), game.get("review_percent"), game.get("review_count"),
                int(bool(game.get("owned"))), int(bool(game.get("wishlisted"))),
                game.get("steam_synced_at"), game.get("verified_at"), now, now,
            ),
        )
        if source:
            connection.execute(
                """INSERT INTO game_sources
                   (steam_app_id,source_kind,source_name,article_title,url,published_at,summary,
                    candidate_reason,discovered_at) VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(steam_app_id,url) DO UPDATE SET
                    source_kind=excluded.source_kind,source_name=excluded.source_name,
                    article_title=excluded.article_title,published_at=excluded.published_at,
                    summary=excluded.summary,candidate_reason=excluded.candidate_reason""",
                (
                    game["steam_app_id"], source["source_kind"], source["source_name"],
                    source.get("article_title"), source["url"], source.get("published_at"),
                    source.get("summary"), source.get("candidate_reason"),
                    source.get("discovered_at") or now,
                ),
            )
        if price:
            connection.execute(
                """INSERT INTO game_prices
                   (steam_app_id,currency,regular_price,current_price,discount_percent,
                    sale_ends_at,source_url,observed_at) VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(steam_app_id,observed_at) DO UPDATE SET
                    currency=excluded.currency,regular_price=excluded.regular_price,
                    current_price=excluded.current_price,discount_percent=excluded.discount_percent,
                    sale_ends_at=excluded.sale_ends_at,source_url=excluded.source_url""",
                (
                    game["steam_app_id"], price["currency"], price.get("regular_price"),
                    price.get("current_price"), price.get("discount_percent"),
                    price.get("sale_ends_at"), price["source_url"], price["observed_at"],
                ),
            )
        connection.commit()


def save_game_candidate(candidate: dict[str, object], db_path: Path = DEFAULT_DB_PATH) -> None:
    now = utc_now()
    with closing(connect(db_path)) as connection:
        connection.execute(
            """INSERT INTO game_candidates
               (id,steam_app_id,cycle_key,candidate_kind,status,total_score,interest_score,
                momentum_score,review_score,price_score,diversity_score,reasons_json,
                exclusion_reason,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(steam_app_id,cycle_key,candidate_kind) DO UPDATE SET
                status=excluded.status,total_score=excluded.total_score,
                interest_score=excluded.interest_score,momentum_score=excluded.momentum_score,
                review_score=excluded.review_score,price_score=excluded.price_score,
                diversity_score=excluded.diversity_score,reasons_json=excluded.reasons_json,
                exclusion_reason=excluded.exclusion_reason,updated_at=excluded.updated_at""",
            (
                candidate["id"], candidate["steam_app_id"], candidate["cycle_key"],
                candidate["candidate_kind"], candidate["status"], candidate["total_score"],
                candidate["interest_score"], candidate["momentum_score"], candidate["review_score"],
                candidate["price_score"], candidate["diversity_score"], candidate["reasons_json"],
                candidate.get("exclusion_reason"), now, now,
            ),
        )
        connection.commit()


def record_game_decision(
    steam_app_id: str, decision: str, note: str | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    if not steam_app_id.isascii() or not steam_app_id.isdigit():
        raise ValueError("Steam App IDが正しくありません。")
    if decision not in {"play_candidate", "article_candidate", "hold", "not_interested"}:
        raise ValueError("候補の判断が正しくありません。")
    cleaned_note = note.strip() if note else None
    if cleaned_note and len(cleaned_note) > 500:
        raise ValueError("候補のメモが長すぎます。")
    with closing(connect(db_path)) as connection:
        if connection.execute("SELECT 1 FROM games WHERE steam_app_id=?", (steam_app_id,)).fetchone() is None:
            raise ValueError("対象ゲームが見つかりません。")
        connection.execute(
            "INSERT INTO game_decisions(steam_app_id,decision,note,created_at) VALUES (?,?,?,?)",
            (steam_app_id, decision, cleaned_note, utc_now()),
        )
        connection.commit()


def start_game_collection_run(
    run_id: str, run_kind: str, item_limit: int, db_path: Path = DEFAULT_DB_PATH,
) -> None:
    with closing(connect(db_path)) as connection:
        connection.execute(
            """INSERT INTO game_collection_runs
               (id,run_kind,status,item_limit,safe_message,started_at)
               VALUES (?,?,'running',?,'収集を開始しました。',?)""",
            (run_id, run_kind, item_limit, utc_now()),
        )
        connection.commit()


def finish_game_collection_run(
    run_id: str, status: str, safe_message: str, *, items_discovered: int = 0,
    items_stored: int = 0, apify_items: int = 0, apify_cost_usd: float = 0,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    with closing(connect(db_path)) as connection:
        cursor = connection.execute(
            """UPDATE game_collection_runs SET status=?,items_discovered=?,items_stored=?,
               apify_items=?,apify_cost_usd=?,safe_message=?,completed_at=?
               WHERE id=? AND status='running'""",
            (status, items_discovered, items_stored, apify_items, apify_cost_usd,
             safe_message, utc_now(), run_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("実行中の収集記録が見つかりません。")
        connection.commit()


def game_information_summary(db_path: Path = DEFAULT_DB_PATH) -> dict[str, object]:
    with closing(connect(db_path)) as connection:
        games = int(connection.execute("SELECT COUNT(*) FROM games").fetchone()[0])
        candidates = int(connection.execute(
            "SELECT COUNT(*) FROM game_candidates WHERE status='active'"
        ).fetchone()[0])
        unconfirmed = int(connection.execute(
            "SELECT COUNT(*) FROM game_candidates WHERE status='unconfirmed'"
        ).fetchone()[0])
        sources = int(connection.execute("SELECT COUNT(*) FROM game_sources").fetchone()[0])
        prices = int(connection.execute("SELECT COUNT(*) FROM game_prices").fetchone()[0])
        last_run = connection.execute(
            "SELECT * FROM game_collection_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    return {
        "games": games, "candidates": candidates, "unconfirmed": unconfirmed,
        "sources": sources, "prices": prices, "last_run": dict(last_run) if last_run else None,
    }


def list_game_candidates(db_path: Path = DEFAULT_DB_PATH, limit: int = 50) -> list[dict[str, object]]:
    safe_limit = min(max(limit, 1), 100)
    with closing(connect(db_path)) as connection:
        rows = connection.execute(
            """SELECT game_candidates.*,games.title,games.store_url,games.japanese_support,
                      games.japan_availability,games.single_player,games.owned,games.wishlisted,
                      (SELECT decision FROM game_decisions
                       WHERE game_decisions.steam_app_id=game_candidates.steam_app_id
                       ORDER BY created_at DESC,id DESC LIMIT 1) AS latest_decision
               FROM game_candidates JOIN games USING(steam_app_id)
               ORDER BY game_candidates.cycle_key DESC,game_candidates.total_score DESC,
                        games.title COLLATE NOCASE LIMIT ?""",
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


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


def import_analytics_rows(
    rows: list[dict[str, object]], source: str, filename: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    now = utc_now()
    days = [str(item["day"]) for item in rows]
    with closing(connect(db_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        for item in rows:
            connection.execute(
                """INSERT INTO analytics_daily(day,path,views,visitors,source,imported_at)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(day,path,source) DO UPDATE SET
                   views=excluded.views,visitors=excluded.visitors,imported_at=excluded.imported_at""",
                (str(item["day"]), str(item["path"]), int(item["views"]), int(item["visitors"]), source, now),
            )
        connection.execute(
            """INSERT INTO analytics_imports
               (source,filename,row_count,period_start,period_end,result,safe_message,created_at)
               VALUES (?,?,?,?,?,'success','解析データを取り込みました。',?)""",
            (source, filename, len(rows), min(days) if days else None, max(days) if days else None, now),
        )
        connection.commit()


def analytics_summary(start: str, end: str, db_path: Path = DEFAULT_DB_PATH) -> dict[str, object]:
    with closing(connect(db_path)) as connection:
        total = connection.execute(
            """SELECT COALESCE(SUM(views),0) views,COALESCE(SUM(visitors),0) visitors
               FROM analytics_daily WHERE day BETWEEN ? AND ?""",
            (start, end),
        ).fetchone()
        daily = connection.execute(
            """SELECT day,SUM(views) views,SUM(visitors) visitors FROM analytics_daily
               WHERE day BETWEEN ? AND ? GROUP BY day ORDER BY day""",
            (start, end),
        ).fetchall()
        pages = connection.execute(
            """SELECT path,SUM(views) views,SUM(visitors) visitors FROM analytics_daily
               WHERE day BETWEEN ? AND ? GROUP BY path ORDER BY views DESC,path LIMIT 20""",
            (start, end),
        ).fetchall()
    return {
        "views": int(total["views"]), "visitors": int(total["visitors"]),
        "daily": [dict(row) for row in daily], "pages": [dict(row) for row in pages],
    }


def recent_analytics_imports(db_path: Path = DEFAULT_DB_PATH, limit: int = 10) -> list[dict[str, object]]:
    with closing(connect(db_path)) as connection:
        rows = connection.execute(
            "SELECT * FROM analytics_imports ORDER BY id DESC LIMIT ?", (min(max(limit, 1), 50),)
        ).fetchall()
    return [dict(row) for row in rows]


def create_social_draft(
    draft_id: str, article_id: str, article_file_hash: str, message: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    now = utc_now()
    with closing(connect(db_path)) as connection:
        connection.execute(
            """INSERT INTO social_drafts
               (id,article_id,article_file_hash,message,status,created_at,updated_at)
               VALUES (?,?,?,?,'draft',?,?)""",
            (draft_id, article_id, article_file_hash, message, now, now),
        )
        connection.commit()


def list_social_drafts(db_path: Path = DEFAULT_DB_PATH) -> list[dict[str, object]]:
    with closing(connect(db_path)) as connection:
        rows = connection.execute(
            """SELECT social_drafts.*,articles.slug,articles.source_path
               FROM social_drafts JOIN articles ON articles.id=social_drafts.article_id
               ORDER BY social_drafts.updated_at DESC"""
        ).fetchall()
    return [dict(row) for row in rows]


def get_social_draft(draft_id: str, db_path: Path = DEFAULT_DB_PATH) -> dict[str, object] | None:
    with closing(connect(db_path)) as connection:
        row = connection.execute("SELECT * FROM social_drafts WHERE id=?", (draft_id,)).fetchone()
    return dict(row) if row else None


def update_social_draft(draft_id: str, message: str, db_path: Path = DEFAULT_DB_PATH) -> None:
    with closing(connect(db_path)) as connection:
        cursor = connection.execute(
            """UPDATE social_drafts SET message=?,status='draft',reviewed_at=NULL,
               platform=NULL,posted_url=NULL,posted_at=NULL,updated_at=? WHERE id=?""",
            (message, utc_now(), draft_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("SNS投稿案が見つかりません。")
        connection.commit()


def review_social_draft(draft_id: str, db_path: Path = DEFAULT_DB_PATH) -> None:
    now = utc_now()
    with closing(connect(db_path)) as connection:
        cursor = connection.execute(
            "UPDATE social_drafts SET status='reviewed',reviewed_at=?,updated_at=? WHERE id=? AND status='draft'",
            (now, now, draft_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("下書き状態のSNS投稿案が見つかりません。")
        connection.commit()


def mark_social_draft_posted(
    draft_id: str, platform: str, posted_url: str | None,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    now = utc_now()
    with closing(connect(db_path)) as connection:
        cursor = connection.execute(
            """UPDATE social_drafts SET status='posted',platform=?,posted_url=?,posted_at=?,updated_at=?
               WHERE id=? AND status='reviewed'""",
            (platform, posted_url, now, now, draft_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("確認済みのSNS投稿案が見つかりません。")
        connection.commit()


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


def register_imported_published_article(
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
                last_saved_at, published_at, published_file_hash, revision, created_at, updated_at)
               VALUES (?, ?, ?, 'published', ?, ?, ?, ?, ?, 1, ?, ?)""",
            (article_id, slug, article_type, source_path, file_hash, now, now, file_hash, now, now),
        )
        connection.execute(
            """INSERT INTO article_events
               (article_id,event_type,to_state,result,file_hash,message_code,safe_message,created_at)
               VALUES (?,'public_import','published','success',?,'public_article_imported','公開中の記事を管理画面へ取り込みました。',?)""",
            (article_id, file_hash, now),
        )
        connection.commit()


def reconcile_published_article(article_id: str, file_hash: str, db_path: Path = DEFAULT_DB_PATH) -> None:
    now = utc_now()
    with closing(connect(db_path)) as connection:
        connection.execute(
            """UPDATE articles SET state='published',previous_state=NULL,published_at=COALESCE(published_at,?),
               published_file_hash=?,updated_at=? WHERE id=? AND file_hash=?""",
            (now, file_hash, now, article_id, file_hash),
        )
        connection.execute(
            """INSERT INTO article_events
               (article_id,event_type,to_state,result,file_hash,message_code,safe_message,created_at)
               VALUES (?,'reconcile','published','success',?,'public_copy_matched','公開中の内容と一致する状態へ戻しました。',?)""",
            (article_id, file_hash, now),
        )
        connection.commit()


def mark_unpublished_archived(article_id: str, db_path: Path = DEFAULT_DB_PATH) -> None:
    now = utc_now()
    with closing(connect(db_path)) as connection:
        row = connection.execute("SELECT file_hash FROM articles WHERE id=?", (article_id,)).fetchone()
        if row is None:
            raise RuntimeError("記事が見つかりません。")
        connection.execute(
            """UPDATE articles SET state='archived',previous_state='draft',archived_at=?,
               published_at=NULL,published_file_hash=NULL,updated_at=? WHERE id=?""",
            (now, now, article_id),
        )
        connection.execute(
            """INSERT INTO article_events
               (article_id,event_type,from_state,to_state,result,file_hash,message_code,safe_message,created_at)
               VALUES (?,'unpublish','published','archived','success',?,'article_unpublished','公開を停止し、記事を削除済みに移しました。',?)""",
            (article_id, str(row["file_hash"]), now),
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


def list_calendar_articles(db_path: Path = DEFAULT_DB_PATH) -> list[dict[str, object]]:
    with closing(connect(db_path)) as connection:
        rows = connection.execute(
            """SELECT * FROM articles
               WHERE state != 'archived' AND (scheduled_at IS NOT NULL OR published_at IS NOT NULL)
               ORDER BY COALESCE(scheduled_at, published_at), slug COLLATE NOCASE"""
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
            """UPDATE articles SET article_type = ?, state = 'draft',
               previous_state = CASE WHEN state = 'published' OR previous_state = 'published' THEN 'published' ELSE NULL END,
               file_hash = ?, last_saved_at = ?, revision = revision + 1, updated_at = ?,
               reviewed_file_hash = NULL, scheduled_at = NULL, scheduled_file_hash = NULL,
               scheduled_claimed_at = NULL, schedule_error = NULL
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


def mark_reviewed(article_id: str, file_hash: str, db_path: Path = DEFAULT_DB_PATH) -> None:
    now = utc_now()
    with closing(connect(db_path)) as connection:
        cursor = connection.execute(
            """UPDATE articles SET state = 'review_pending', last_reviewed_at = ?,
               reviewed_file_hash = ?, updated_at = ? WHERE id = ? AND file_hash = ?""",
            (now, file_hash, now, article_id, file_hash),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("校正中に記事が変更されました。")
        connection.execute(
            """INSERT INTO article_events
               (article_id,event_type,to_state,result,file_hash,message_code,safe_message,created_at)
               VALUES (?,'review','review_pending','success',?,'review_completed','校正結果を保存しました。',?)""",
            (article_id, file_hash, now),
        )
        connection.commit()


def mark_ready(article_id: str, file_hash: str, db_path: Path = DEFAULT_DB_PATH) -> None:
    now = utc_now()
    with closing(connect(db_path)) as connection:
        cursor = connection.execute(
            """UPDATE articles SET state='ready',updated_at=?
               WHERE id=? AND file_hash=?""",
            (now, article_id, file_hash),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("公開前チェック後に記事の状態が変わりました。")
        connection.commit()


def mark_scheduled(article_id: str, file_hash: str, scheduled_at: str, db_path: Path = DEFAULT_DB_PATH) -> None:
    now = utc_now()
    with closing(connect(db_path)) as connection:
        row = connection.execute("SELECT state FROM articles WHERE id=? AND file_hash=?", (article_id, file_hash)).fetchone()
        if row is None or str(row["state"]) != "ready":
            raise RuntimeError("予約確定前に記事または状態が変わりました。")
        connection.execute(
            """UPDATE articles SET state='scheduled',scheduled_at=?,scheduled_file_hash=?,
               scheduled_claimed_at=NULL,schedule_error=NULL,updated_at=? WHERE id=? AND file_hash=?""",
            (scheduled_at, file_hash, now, article_id, file_hash),
        )
        connection.execute(
            """INSERT INTO article_events
               (article_id,event_type,from_state,to_state,result,file_hash,message_code,safe_message,created_at)
               VALUES (?,'schedule','ready','scheduled','success',?,'article_scheduled','記事の公開を予約しました。',?)""",
            (article_id, file_hash, now),
        )
        connection.commit()


def cancel_schedule(article_id: str, db_path: Path = DEFAULT_DB_PATH) -> None:
    now = utc_now()
    with closing(connect(db_path)) as connection:
        row = connection.execute("SELECT state,file_hash FROM articles WHERE id=?", (article_id,)).fetchone()
        if row is None or str(row["state"]) != "scheduled":
            raise RuntimeError("解除できる予約がありません。")
        connection.execute(
            """UPDATE articles SET state='ready',scheduled_at=NULL,scheduled_file_hash=NULL,
               scheduled_claimed_at=NULL,schedule_error=NULL,updated_at=? WHERE id=?""",
            (now, article_id),
        )
        connection.execute(
            """INSERT INTO article_events
               (article_id,event_type,from_state,to_state,result,file_hash,message_code,safe_message,created_at)
               VALUES (?,'schedule_cancel','scheduled','ready','success',?,'schedule_cancelled','記事の公開予約を解除しました。',?)""",
            (article_id, str(row["file_hash"]), now),
        )
        connection.commit()


def claim_due_schedules(now: str, db_path: Path = DEFAULT_DB_PATH) -> list[dict[str, object]]:
    claimed: list[dict[str, object]] = []
    with closing(connect(db_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            """SELECT * FROM articles WHERE state='scheduled' AND scheduled_at<=?
               AND scheduled_claimed_at IS NULL ORDER BY scheduled_at""",
            (now,),
        ).fetchall()
        for row in rows:
            cursor = connection.execute(
                "UPDATE articles SET scheduled_claimed_at=?,updated_at=? WHERE id=? AND scheduled_claimed_at IS NULL",
                (now, now, str(row["id"])),
            )
            if cursor.rowcount == 1:
                item = dict(row)
                item["scheduled_claimed_at"] = now
                claimed.append(item)
        connection.commit()
    return claimed


def fail_schedule(article_id: str, message: str, db_path: Path = DEFAULT_DB_PATH) -> None:
    now = utc_now()
    with closing(connect(db_path)) as connection:
        row = connection.execute("SELECT state,file_hash FROM articles WHERE id=?", (article_id,)).fetchone()
        if row is None:
            return
        connection.execute(
            """UPDATE articles SET state='ready',scheduled_at=NULL,scheduled_file_hash=NULL,
               scheduled_claimed_at=NULL,schedule_error=?,updated_at=? WHERE id=?""",
            (message, now, article_id),
        )
        connection.execute(
            """INSERT INTO article_events
               (article_id,event_type,from_state,to_state,result,file_hash,message_code,safe_message,created_at)
               VALUES (?,'scheduled_publish',?,'ready','failure',?,'scheduled_publish_failed',?,?)""",
            (article_id, str(row["state"]), str(row["file_hash"]), message, now),
        )
        connection.commit()


def restore_after_precommit_publish_failure(article_id: str, file_hash: str, db_path: Path = DEFAULT_DB_PATH) -> None:
    now = utc_now()
    with closing(connect(db_path)) as connection:
        row = connection.execute("SELECT state,published_at FROM articles WHERE id=? AND file_hash=?", (article_id, file_hash)).fetchone()
        if row is None or str(row["state"]) != "ready":
            return
        previous = "published" if row["published_at"] else None
        connection.execute(
            "UPDATE articles SET state='draft',previous_state=?,updated_at=? WHERE id=? AND file_hash=?",
            (previous, now, article_id, file_hash),
        )
        connection.execute(
            """INSERT INTO article_events
               (article_id,event_type,from_state,to_state,result,file_hash,message_code,safe_message,created_at)
               VALUES (?,'publish','ready','draft','warning',?,'publish_reverted_to_draft','投稿失敗後に更新下書きへ戻しました。',?)""",
            (article_id, file_hash, now),
        )
        connection.commit()


def create_publish_attempt(attempt_id: str, article_id: str, file_hash: str, token_hash: str, expires_at: str, db_path: Path = DEFAULT_DB_PATH, scheduled_for: str | None = None) -> None:
    with closing(connect(db_path)) as connection:
        connection.execute(
            """INSERT INTO publish_attempts
               (id,article_id,file_hash,token_hash,result,expires_at,created_at,scheduled_for)
               VALUES (?,?,?,?,'checked',?,?,?)""",
            (attempt_id, article_id, file_hash, token_hash, expires_at, utc_now(), scheduled_for),
        )
        connection.commit()


def get_publish_attempt(attempt_id: str, db_path: Path = DEFAULT_DB_PATH) -> dict[str, object] | None:
    with closing(connect(db_path)) as connection:
        row = connection.execute("SELECT * FROM publish_attempts WHERE id=?", (attempt_id,)).fetchone()
    return dict(row) if row else None


def update_publish_attempt(attempt_id: str, result: str, message: str, commit_sha: str | None = None, pages_url: str | None = None, db_path: Path = DEFAULT_DB_PATH) -> None:
    if result not in {"running", "success", "failure", "expired"}:
        raise ValueError("公開結果が正しくありません。")
    completed = utc_now() if result in {"success", "failure", "expired"} else None
    with closing(connect(db_path)) as connection:
        connection.execute(
            """UPDATE publish_attempts SET result=?,safe_message=?,commit_sha=?,pages_url=?,completed_at=? WHERE id=?""",
            (result, message, commit_sha, pages_url, completed, attempt_id),
        )
        connection.commit()


def mark_published(article_id: str, file_hash: str, db_path: Path = DEFAULT_DB_PATH) -> None:
    now = utc_now()
    with closing(connect(db_path)) as connection:
        row = connection.execute("SELECT state FROM articles WHERE id=? AND file_hash=?", (article_id, file_hash)).fetchone()
        from_state = str(row["state"]) if row else "ready"
        cursor = connection.execute(
            """UPDATE articles SET state='published',previous_state=NULL,published_at=?,published_file_hash=?,updated_at=?,
               scheduled_at=NULL,scheduled_file_hash=NULL,scheduled_claimed_at=NULL,schedule_error=NULL
               WHERE id=? AND file_hash=?""",
            (now, file_hash, now, article_id, file_hash),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("公開完了時の記事ハッシュが一致しません。")
        connection.execute(
            """INSERT INTO article_events
               (article_id,event_type,from_state,to_state,result,file_hash,message_code,safe_message,created_at)
               VALUES (?,'publish',?,'published','success',?,'publish_completed','記事を公開しました。',?)""",
            (article_id, from_state, file_hash, now),
        )
        connection.commit()

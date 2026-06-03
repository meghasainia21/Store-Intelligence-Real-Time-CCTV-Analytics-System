
import logging
import os
from typing import Optional

import aiosqlite

logger = logging.getLogger("database")

DB_PATH = os.getenv("DB_PATH", "./store_intelligence.db")
_db: Optional[aiosqlite.Connection] = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        raise RuntimeError("Database not initialised — call init_db() first")
    return _db


async def check_db_health() -> bool:
    try:
        db = await get_db()
        await db.execute("SELECT 1")
        return True
    except Exception:
        return False


async def init_db():
    global _db
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA synchronous=NORMAL")
    await _db.execute("PRAGMA cache_size=10000")
    await _db.execute("PRAGMA foreign_keys=ON")
    await _create_schema()
    logger.info(f"Database ready at {DB_PATH}")


async def _create_schema():
    db = await get_db()
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            event_id     TEXT PRIMARY KEY,
            store_id     TEXT NOT NULL,
            camera_id    TEXT NOT NULL,
            visitor_id   TEXT NOT NULL,
            event_type   TEXT NOT NULL,
            timestamp    TEXT NOT NULL,
            zone_id      TEXT,
            dwell_ms     INTEGER NOT NULL DEFAULT 0,
            is_staff     INTEGER NOT NULL DEFAULT 0,
            confidence   REAL NOT NULL DEFAULT 0.0,
            queue_depth  INTEGER,
            sku_zone     TEXT,
            session_seq  INTEGER NOT NULL DEFAULT 0,
            ingested_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_events_store_ts
            ON events(store_id, timestamp);

        CREATE INDEX IF NOT EXISTS idx_events_store_visitor
            ON events(store_id, visitor_id);

        CREATE INDEX IF NOT EXISTS idx_events_store_type
            ON events(store_id, event_type);

        CREATE TABLE IF NOT EXISTS pos_transactions (
            transaction_id   TEXT PRIMARY KEY,
            store_id         TEXT NOT NULL,
            timestamp        TEXT NOT NULL,
            basket_value_inr REAL NOT NULL,
            visitor_id       TEXT,
            ingested_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_pos_store_ts
            ON pos_transactions(store_id, timestamp);

        CREATE TABLE IF NOT EXISTS anomaly_history (
            anomaly_id    TEXT PRIMARY KEY,
            store_id      TEXT NOT NULL,
            anomaly_type  TEXT NOT NULL,
            severity      TEXT NOT NULL,
            description   TEXT NOT NULL,
            detected_at   TEXT NOT NULL,
            resolved_at   TEXT,
            value         REAL,
            threshold     REAL
        );
    """)
    await db.commit()
    logger.info("Schema created / verified")

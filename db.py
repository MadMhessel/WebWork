# newsbot/db.py
import logging
import os
import sqlite3
from typing import Any, Dict, Optional

from . import config

logger = logging.getLogger(__name__)

# ---------- Connection helpers ----------

def connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Open a SQLite connection. Uses config.DB_PATH by default.
    """
    path = db_path or getattr(config, "DB_PATH", "newsbot.db")
    # Ensure directory exists if path contains folders
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # Reasonable pragmas for a lightweight single-writer, multi-reader workload
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    except Exception:
        pass
    return conn


def _ensure_column(
    conn: sqlite3.Connection, table: str, column: str, col_type: str
) -> None:
    """Ensure that ``table`` has a column named ``column`` of ``col_type``.

    SQLite prior to version 3.35 does not support ``ALTER TABLE ... ADD COLUMN
    IF NOT EXISTS`` so we manually inspect the table schema via
    ``PRAGMA table_info`` and add the column if it is missing.  The function is
    idempotent and commits the change immediately when a column is added.
    """

    cur = conn.execute(f"PRAGMA table_info({table})")
    cols = {row[1] for row in cur.fetchall()}  # row[1] is column name
    if column in cols:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    conn.commit()

def init_schema(conn: sqlite3.Connection) -> None:
    """
    Create minimal schema needed by the bot.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            guid TEXT,
            title TEXT NOT NULL,
            title_hash TEXT,
            content TEXT,
            source TEXT,
            published_at TEXT,
            image_url TEXT,
            added_ts INTEGER DEFAULT (strftime('%s','now'))
        );

        CREATE INDEX IF NOT EXISTS idx_items_guid ON items(guid);
        CREATE INDEX IF NOT EXISTS idx_items_title_hash ON items(title_hash);
        CREATE INDEX IF NOT EXISTS idx_items_source ON items(source);

        CREATE TABLE IF NOT EXISTS moderation_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            guid TEXT,
            url TEXT UNIQUE,
            title TEXT,
            content TEXT,
            published_at TEXT,
            image_url TEXT,
            status TEXT,
            tg_message_id TEXT
        );
        """
    )
    _ensure_column(conn, "items", "image_url", "TEXT")
    _ensure_column(conn, "moderation_queue", "image_url", "TEXT")
    conn.commit()
    logger.info("Схема БД инициализирована в %s", getattr(config, "DB_PATH", "newsbot.db"))

    # Добавляем столбец image_url, если он отсутствует
    try:
        conn.execute("ALTER TABLE items ADD COLUMN image_url TEXT")
        conn.commit()
    except Exception:
        pass

# ---------- Existence checks used by dedup ----------

def exists_url(conn: sqlite3.Connection, url: str) -> bool:
    if not url:
        return False
    cur = conn.execute("SELECT 1 FROM items WHERE url = ? LIMIT 1", (url,))
    return cur.fetchone() is not None

def exists_guid(conn: sqlite3.Connection, guid: str) -> bool:
    if not guid:
        return False
    cur = conn.execute("SELECT 1 FROM items WHERE guid = ? LIMIT 1", (guid,))
    return cur.fetchone() is not None

def exists_title_hash(conn: sqlite3.Connection, title_hash: str) -> bool:
    if not title_hash:
        return False
    cur = conn.execute("SELECT 1 FROM items WHERE title_hash = ? LIMIT 1", (title_hash,))
    return cur.fetchone() is not None

# ---------- Insert helpers ----------

def insert_item(conn: sqlite3.Connection, item: Dict[str, Any]) -> Optional[int]:
    """
    Insert item into items table.
    Returns row id or None if ignored due to UNIQUE(url) conflict.
    Expected keys: url, guid, title, title_hash, content, source, published_at, image_url
    """
    fields = ("url","guid","title","title_hash","content","source","published_at","image_url")
    fields = (
        "url",
        "guid",
        "title",
        "title_hash",
        "content",
        "source",
        "published_at",
        "image_url",
    )
    values = tuple(item.get(k) for k in fields)
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO items (url, guid, title, title_hash, content, source, published_at, image_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    conn.commit()
    rid = cur.lastrowid or None
    return rid

def upsert_item(conn: sqlite3.Connection, item: Dict[str, Any]) -> int:
    """
    Upsert by url if provided, otherwise by guid if provided, otherwise plain insert.
    Returns affected row id (existing id if present, or new id).
    """
    url = (item.get("url") or "").strip()
    guid = (item.get("guid") or "").strip()

    if url:
        # Try to update, if 0 rows then insert
        cur = conn.execute("SELECT id FROM items WHERE url = ? LIMIT 1", (url,))
        row = cur.fetchone()
        if row:
            _update_existing(conn, row["id"], item)
            conn.commit()
            return int(row["id"])

    if guid:
        cur = conn.execute("SELECT id FROM items WHERE guid = ? LIMIT 1", (guid,))
        row = cur.fetchone()
        if row:
            _update_existing(conn, row["id"], item)
            conn.commit()
            return int(row["id"])

    rid = insert_item(conn, item) or -1
    return rid

def _update_existing(conn: sqlite3.Connection, item_id: int, item: Dict[str, Any]) -> None:
    conn.execute(
        """
        UPDATE items
           SET guid = COALESCE(?, guid),
               title = COALESCE(?, title),
               title_hash = COALESCE(?, title_hash),
               content = COALESCE(?, content),
               source = COALESCE(?, source),
               published_at = COALESCE(?, published_at),
               image_url = COALESCE(?, image_url)
         WHERE id = ?
        """,
        (
            item.get("guid"),
            item.get("title"),
            item.get("title_hash"),
            item.get("content"),
            item.get("source"),
            item.get("published_at"),
            item.get("image_url"),
            item_id,
        ),
    )

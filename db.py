# newsbot/db.py
import logging
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

try:
    from . import config
except ImportError:  # pragma: no cover
    import config  # type: ignore

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
            source_id TEXT,
            url TEXT UNIQUE,
            guid TEXT,
            title TEXT,
            summary TEXT,
            content TEXT,
            image_url TEXT,
            image_hash TEXT,
            tg_file_id TEXT,
            credit TEXT,
            status TEXT,
            created_at INTEGER DEFAULT (strftime('%s','now')),
            fetched_at INTEGER,
            reviewed_at INTEGER,
            published_at INTEGER,
            review_message_id TEXT,
            channel_message_id TEXT,
            moderator_user_id INTEGER,
            moderator_comment TEXT,
            attempts INTEGER DEFAULT 0
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_mq_url ON moderation_queue(url);
        CREATE INDEX IF NOT EXISTS idx_mq_status ON moderation_queue(status);

        CREATE TABLE IF NOT EXISTS editor_state (
            user_id INTEGER PRIMARY KEY,
            item_id INTEGER,
            started_at INTEGER DEFAULT (strftime('%s','now'))
        );

        CREATE TABLE IF NOT EXISTS moderation_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER,
            mod_chat_id TEXT,
            message_id TEXT,
            state TEXT,
            created_at INTEGER DEFAULT (strftime('%s','now')),
            updated_at INTEGER DEFAULT (strftime('%s','now'))
        );

        CREATE TABLE IF NOT EXISTS moderation_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER,
            user_id INTEGER,
            action TEXT,
            payload TEXT,
            created_at INTEGER DEFAULT (strftime('%s','now'))
        );

        CREATE TABLE IF NOT EXISTS dedup (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            guid TEXT,
            title_hash TEXT,
            added_ts INTEGER DEFAULT (strftime('%s','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_dedup_guid ON dedup(guid);
        CREATE INDEX IF NOT EXISTS idx_dedup_title_hash ON dedup(title_hash);
        """
    )

    _ensure_column(conn, "items", "image_url", "TEXT")
    # --- moderation_queue extra fields for enhanced moderation ---
    _ensure_column(conn, "moderation_queue", "tags", "TEXT")
    _ensure_column(conn, "moderation_queue", "resume_at", "INTEGER")
    _ensure_column(conn, "moderation_queue", "preview_chat_id", "TEXT")
    _ensure_column(conn, "moderation_queue", "risk", "TEXT")
    _ensure_column(conn, "moderation_queue", "reasons", "TEXT")
    _ensure_column(conn, "moderation_queue", "approved_by", "INTEGER")
    _ensure_column(conn, "moderation_queue", "published_msg_id", "TEXT")
    _ensure_column(conn, "moderation_queue", "image_type", "TEXT")
    _ensure_column(conn, "moderation_queue", "image_ref", "TEXT")
    _ensure_column(conn, "moderation_queue", "credit", "TEXT")
    # editor_state now tracks which field is being edited
    _ensure_column(conn, "editor_state", "field", "TEXT")

    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO dedup (url, guid, title_hash, added_ts)
            SELECT url, guid, title_hash, added_ts FROM items
            """
        )
    except Exception:
        pass

    logger.info(
        "Схема БД инициализирована в %s", getattr(config, "DB_PATH", "newsbot.db")
    )
    conn.commit()


def _normalize_url(u: str) -> str:
    if not u:
        return ""
    p = urlparse(u)
    scheme = p.scheme.lower()
    netloc = p.netloc.lower()
    path = p.path.rstrip("/")
    q = [
        (k, v)
        for k, v in parse_qsl(p.query)
        if not (k.lower().startswith("utm_") or k.lower() in {"yclid", "fbclid"})
    ]
    query = urlencode(q, doseq=True)
    return urlunparse((scheme, netloc, path, "", query, ""))


# ---------- Existence checks used by dedup ----------

def exists_url(conn: sqlite3.Connection, url: str) -> bool:
    if not url:
        return False
    cur = conn.execute("SELECT 1 FROM dedup WHERE url = ? LIMIT 1", (url,))
    return cur.fetchone() is not None

def exists_guid(conn: sqlite3.Connection, guid: str) -> bool:
    if not guid:
        return False
    cur = conn.execute("SELECT 1 FROM dedup WHERE guid = ? LIMIT 1", (guid,))
    return cur.fetchone() is not None

def exists_title_hash(conn: sqlite3.Connection, title_hash: str) -> bool:
    if not title_hash:
        return False
    cur = conn.execute("SELECT 1 FROM dedup WHERE title_hash = ? LIMIT 1", (title_hash,))
    return cur.fetchone() is not None


def fetch_recent_titles(
    conn: sqlite3.Connection, since_ts: int, limit: int
) -> List[Tuple[str, str]]:
    """Return recent titles and their hashes from the items table."""

    cur = conn.execute(
        """
        SELECT title, title_hash
          FROM items
         WHERE added_ts IS NULL OR added_ts >= ?
         ORDER BY COALESCE(added_ts, 0) DESC
         LIMIT ?
        """,
        (since_ts, limit),
    )
    rows = cur.fetchall()
    return [((row["title"] or ""), (row["title_hash"] or "")) for row in rows]

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
    conn.execute(
        "INSERT OR IGNORE INTO dedup(url, guid, title_hash) VALUES (?,?,?)",
        (item.get("url"), item.get("guid"), item.get("title_hash")),
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
            conn.execute(
                "INSERT OR IGNORE INTO dedup(url, guid, title_hash) VALUES (?,?,?)",
                (item.get("url"), item.get("guid"), item.get("title_hash")),
            )
            conn.commit()
            return int(row["id"])

    if guid:
        cur = conn.execute("SELECT id FROM items WHERE guid = ? LIMIT 1", (guid,))
        row = cur.fetchone()
        if row:
            _update_existing(conn, row["id"], item)
            conn.execute(
                "INSERT OR IGNORE INTO dedup(url, guid, title_hash) VALUES (?,?,?)",
                (item.get("url"), item.get("guid"), item.get("title_hash")),
            )
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


# ---------- Maintenance helpers ----------

def _prune_table(
    conn: sqlite3.Connection,
    table: str,
    ts_column: str,
    cutoff_ts: int,
    limit: int,
) -> int:
    """Delete up to ``limit`` rows older than ``cutoff_ts`` from ``table``."""

    cur = conn.execute(
        f"SELECT id FROM {table} "
        f"WHERE {ts_column} IS NOT NULL AND {ts_column} < ? "
        f"ORDER BY {ts_column} ASC LIMIT ?",
        (cutoff_ts, limit),
    )
    ids = [row[0] for row in cur.fetchall()]
    if not ids:
        return 0
    conn.executemany(
        f"DELETE FROM {table} WHERE id = ?",
        ((item_id,) for item_id in ids),
    )
    conn.commit()
    return len(ids)


def prune_old_records(
    conn: sqlite3.Connection,
    *,
    items_ttl_days: int,
    dedup_ttl_days: int,
    batch_limit: int = 500,
) -> Dict[str, int]:
    """Purge aged rows from ``items`` and ``dedup`` tables."""

    batch_limit = max(1, int(batch_limit or 0))
    now = int(time.time())
    removed = {"items": 0, "dedup": 0}

    if items_ttl_days > 0:
        cutoff = now - int(items_ttl_days * 86400)
        removed["items"] = _prune_table(conn, "items", "added_ts", cutoff, batch_limit)

    if dedup_ttl_days > 0:
        cutoff = now - int(dedup_ttl_days * 86400)
        removed["dedup"] = _prune_table(conn, "dedup", "added_ts", cutoff, batch_limit)

    if removed["items"] or removed["dedup"]:
        logger.info(
            "Очистка БД: удалено items=%d, dedup=%d",
            removed["items"],
            removed["dedup"],
        )

    return removed

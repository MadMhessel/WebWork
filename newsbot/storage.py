import os
import sqlite3
import hashlib
from typing import Optional

DB_PATH = os.getenv('DB_PATH', 'newsbot.db')

_CONN: Optional[sqlite3.Connection] = None


def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection and ensure schema exists."""
    global _CONN
    if _CONN is None:
        _CONN = sqlite3.connect(DB_PATH)
        create_tables(_CONN)
    return _CONN


def create_tables(conn: sqlite3.Connection) -> None:
    """Create required tables if they do not exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS published_news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            guid TEXT,
            title_norm_hash TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_published_news_guid ON published_news(guid)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_published_news_title_hash ON published_news(title_norm_hash)"
    )
    conn.commit()


def _title_hash(title: str) -> str:
    return hashlib.sha256(title.lower().encode('utf-8')).hexdigest()


def is_published(url: Optional[str] = None, guid: Optional[str] = None, title: Optional[str] = None) -> bool:
    """Check whether the item has already been published."""
    conn = get_connection()
    title_hash = _title_hash(title) if title else None
    cur = conn.execute(
        "SELECT 1 FROM published_news WHERE url = ? OR guid = ? OR title_norm_hash = ?",
        (url, guid, title_hash),
    )
    return cur.fetchone() is not None


def mark_published(url: Optional[str] = None, guid: Optional[str] = None, title: Optional[str] = None) -> None:
    """Record a publication in the database."""
    conn = get_connection()
    title_hash = _title_hash(title) if title else None
    conn.execute(
        "INSERT OR IGNORE INTO published_news (url, guid, title_norm_hash) VALUES (?, ?, ?)",
        (url, guid, title_hash),
    )
    conn.commit()

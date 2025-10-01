from __future__ import annotations

# import-shim: allow running as a script (no package parent)
if __name__ == "__main__" or __package__ is None:
    import os
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
# end of shim

import logging
import sqlite3
import time

import config


_LOG = logging.getLogger("webwork.raw")
_CONN: sqlite3.Connection | None = None


def get_conn() -> sqlite3.Connection:
    global _CONN
    if _CONN is None:
        db_path = getattr(config, "SEEN_DB_PATH", "seen.sqlite3")
        _CONN = sqlite3.connect(db_path)
        _CONN.row_factory = sqlite3.Row
        _ensure_schema(_CONN)
        if getattr(config, "RAW_DEDUP_LOG", True):
            _LOG.debug("[RAW] открыт seen-store: %s", db_path)
    return _CONN


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seen_items (
          key TEXT PRIMARY KEY,
          first_seen INTEGER NOT NULL,
          source_domain TEXT,
          title TEXT
        )
        """
    )
    conn.commit()


def is_seen(conn: sqlite3.Connection, key: str) -> bool:
    cur = conn.execute("SELECT 1 FROM seen_items WHERE key = ?", (key,))
    result = cur.fetchone() is not None
    if getattr(config, "RAW_DEDUP_LOG", True):
        _LOG.debug("[RAW] проверка seen: %s -> %s", key, result)
    return result


def mark_seen(
    conn: sqlite3.Connection,
    key: str,
    *,
    source_domain: str = "",
    title: str = "",
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO seen_items (key, first_seen, source_domain, title) "
        "VALUES (?, ?, ?, ?)",
        (key, int(time.time()), source_domain, title),
    )
    conn.commit()
    if getattr(config, "RAW_DEDUP_LOG", True):
        _LOG.debug("[RAW] сохранён ключ: %s", key)

import logging
import sqlite3
import time
from typing import Any, Dict, Optional

from . import config, publisher

logger = logging.getLogger(__name__)

PENDING_REVIEW = "PENDING_REVIEW"
REJECTED = "REJECTED"
SNOOZED = "SNOOZED"
APPROVED = "APPROVED"
PUBLISHED = "PUBLISHED"


def is_moderator(user_id: int) -> bool:
    try:
        return int(user_id) in getattr(config, "MODERATOR_IDS", set())
    except Exception:
        return False


def enqueue_item(item: Dict[str, Any], conn: sqlite3.Connection) -> Optional[int]:
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO moderation_queue
        (source_id, url, guid, title, summary, content, image_url, image_hash, tg_file_id, status, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s','now'))
        """,
        (
            item.get("source_id"),
            item.get("url"),
            item.get("guid"),
            item.get("title"),
            item.get("summary"),
            item.get("content"),
            item.get("image_url"),
            item.get("image_hash"),
            item.get("tg_file_id"),
            PENDING_REVIEW,
        ),
    )
    if cur.rowcount == 0:
        cur2 = conn.execute("SELECT id FROM moderation_queue WHERE url = ?", (item.get("url"),))
        row = cur2.fetchone()
        return int(row["id"]) if row else None
    mod_id = int(cur.lastrowid)
    conn.commit()
    logger.info("[QUEUED] id=%d | %s", mod_id, (item.get("title") or "")[:140])
    return mod_id


def get_item(conn: sqlite3.Connection, mod_id: int) -> Optional[Dict[str, Any]]:
    cur = conn.execute("SELECT * FROM moderation_queue WHERE id = ?", (mod_id,))
    row = cur.fetchone()
    return dict(row) if row else None


def send_preview(conn: sqlite3.Connection, mod_id: int) -> Optional[str]:
    item = get_item(conn, mod_id)
    if not item:
        return None
    chat_id = getattr(config, "REVIEW_CHAT_ID", "")
    if not chat_id:
        return None
    mid = publisher.send_moderation_preview(chat_id, item, mod_id, cfg=config)
    if mid:
        conn.execute(
            "UPDATE moderation_queue SET review_message_id = ? WHERE id = ?",
            (mid, mod_id),
        )
        conn.commit()
    return mid


def enqueue_and_preview(item: Dict[str, Any], conn: sqlite3.Connection) -> Optional[int]:
    mod_id = enqueue_item(item, conn)
    if mod_id:
        send_preview(conn, mod_id)
    return mod_id


def approve(conn: sqlite3.Connection, mod_id: int, moderator_id: int, text_override: Optional[str] = None) -> bool:
    if not is_moderator(moderator_id):
        return False
    conn.execute(
        "UPDATE moderation_queue SET status = ?, reviewed_at = strftime('%s','now'), moderator_user_id = ? WHERE id = ?",
        (APPROVED, moderator_id, mod_id),
    )
    conn.commit()
    mid = publisher.publish_from_queue(conn, mod_id, text_override=text_override, cfg=config)
    return bool(mid)


def reject(conn: sqlite3.Connection, mod_id: int, moderator_id: int, comment: str = "") -> bool:
    if not is_moderator(moderator_id):
        return False
    conn.execute(
        "UPDATE moderation_queue SET status = ?, reviewed_at = strftime('%s','now'), moderator_user_id = ?, moderator_comment = ? WHERE id = ?",
        (REJECTED, moderator_id, comment, mod_id),
    )
    conn.commit()
    return True


def snooze(conn: sqlite3.Connection, mod_id: int, moderator_id: int) -> bool:
    if not is_moderator(moderator_id):
        return False
    conn.execute(
        "UPDATE moderation_queue SET status = ?, reviewed_at = strftime('%s','now'), moderator_user_id = ?, attempts = attempts + 1 WHERE id = ?",
        (SNOOZED, moderator_id, mod_id),
    )
    conn.commit()
    return True

import logging
import sqlite3
import time
from typing import Any, Dict, Optional

try:
    from . import config, publisher, db
except ImportError:  # pragma: no cover
    import config, publisher, db  # type: ignore

logger = logging.getLogger(__name__)

PENDING_REVIEW = "PENDING_REVIEW"
REJECTED = "REJECTED"
SNOOZED = "SNOOZED"
APPROVED = "APPROVED"
PUBLISHED = "PUBLISHED"
EDITING = "EDITING"


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
    cur = conn.execute(
        "UPDATE moderation_queue SET status = ?, reviewed_at = strftime('%s','now'), moderator_user_id = ? WHERE id = ? AND status IN ('PENDING_REVIEW','SNOOZED')",
        (APPROVED, moderator_id, mod_id),
    )
    if cur.rowcount == 0:
        conn.commit()
        return False
    conn.commit()
    mid = publisher.publish_from_queue(conn, mod_id, text_override=text_override, cfg=config)
    return bool(mid)


def reject(conn: sqlite3.Connection, mod_id: int, moderator_id: int, comment: str = "") -> bool:
    if not is_moderator(moderator_id):
        return False
    cur = conn.execute(
        "UPDATE moderation_queue SET status = ?, reviewed_at = strftime('%s','now'), moderator_user_id = ?, moderator_comment = ? WHERE id = ? AND status IN ('PENDING_REVIEW','SNOOZED')",
        (REJECTED, moderator_id, comment, mod_id),
    )
    conn.commit()
    return cur.rowcount > 0


def snooze(conn: sqlite3.Connection, mod_id: int, moderator_id: int) -> bool:
    if not is_moderator(moderator_id):
        return False
    cur = conn.execute(
        "UPDATE moderation_queue SET status = ?, reviewed_at = strftime('%s','now'), moderator_user_id = ?, attempts = attempts + 1 WHERE id = ? AND status IN ('PENDING_REVIEW','SNOOZED')",
        (SNOOZED, moderator_id, mod_id),
    )
    conn.commit()
    return cur.rowcount > 0


def start_edit(conn: sqlite3.Connection, mod_id: int, moderator_id: int) -> bool:
    if not is_moderator(moderator_id):
        return False
    conn.execute(
        "INSERT OR REPLACE INTO editor_state(user_id, item_id, started_at) VALUES (?,?,strftime('%s','now'))",
        (moderator_id, mod_id),
    )
    conn.commit()
    return True


def cancel_edit(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute("DELETE FROM editor_state WHERE user_id = ?", (user_id,))
    conn.commit()


def apply_edit_message(conn: sqlite3.Connection, user_id: int, text: str) -> bool:
    cur = conn.execute("SELECT item_id FROM editor_state WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        return False
    mod_id = int(row["item_id"])
    conn.execute(
        "UPDATE moderation_queue SET content = ?, status = ? WHERE id = ?",
        (text, PENDING_REVIEW, mod_id),
    )
    conn.execute("DELETE FROM editor_state WHERE user_id = ?", (user_id,))
    conn.commit()
    send_preview(conn, mod_id)
    return True


def handle_callback(conn: sqlite3.Connection, update: dict) -> None:
    cb = update.get("callback_query") or {}
    data = cb.get("data", "")
    user_id = int(cb.get("from", {}).get("id", 0))
    if not data.startswith("mod:"):
        return
    try:
        _, sid, action = data.split(":", 2)
        mod_id = int(sid)
    except Exception:
        return
    if not is_moderator(user_id):
        return
    if action == "approve":
        approve(conn, mod_id, user_id)
    elif action == "reject":
        reject(conn, mod_id, user_id)
    elif action == "snooze":
        snooze(conn, mod_id, user_id)
    elif action == "edit":
        start_edit(conn, mod_id, user_id)


def cmd_queue(conn: sqlite3.Connection, chat_id: str, page: int = 1) -> None:
    limit = 10
    offset = (page - 1) * limit
    cur = conn.execute(
        "SELECT id, title FROM moderation_queue WHERE status IN (?,?) ORDER BY id LIMIT ? OFFSET ?",
        (PENDING_REVIEW, SNOOZED, limit, offset),
    )
    rows = cur.fetchall()
    lines = [f"{r['id']}: {r['title'] or ''}" for r in rows]
    text = "\n".join(lines) or "Очередь пуста"
    publisher.send_message(str(chat_id), text, cfg=config)


def cmd_approve(conn: sqlite3.Connection, mod_id: int, user_id: int) -> None:
    if approve(conn, mod_id, user_id):
        publisher.send_message(str(user_id), f"Approved {mod_id}", cfg=config)


def cmd_reject(conn: sqlite3.Connection, mod_id: int, user_id: int, reason: Optional[str] = None) -> None:
    if reject(conn, mod_id, user_id, reason or ""):
        publisher.send_message(str(user_id), f"Rejected {mod_id}", cfg=config)


def cmd_stats(conn: sqlite3.Connection, chat_id: str) -> None:
    cur = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM moderation_queue GROUP BY status",
    )
    parts = [f"{row['status']}: {row['cnt']}" for row in cur.fetchall()]
    text = "\n".join(parts)
    publisher.send_message(str(chat_id), text, cfg=config)

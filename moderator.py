import json
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
SKIPPED = "SKIPPED"  # очередь возвращается позже
EDITING = "EDITING"


def is_moderator(user_id: int) -> bool:
    try:
        allowed = set(getattr(config, "ALLOWED_MODERATORS", set()))
        allowed |= set(getattr(config, "MODERATOR_IDS", set()))
        return int(user_id) in allowed
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
        conn.execute(
            """
            INSERT OR REPLACE INTO moderation_messages
            (post_id, mod_chat_id, message_id, state, created_at, updated_at)
            VALUES(?, ?, ?, 'new', strftime('%s','now'), strftime('%s','now'))
            """,
            (mod_id, str(chat_id), str(mid)),
        )
        conn.commit()
        logger.info(
            "preview", extra={"post_id": mod_id, "chat_id": chat_id, "message_id": mid}
        )
    return mid


def enqueue_and_preview(item: Dict[str, Any], conn: sqlite3.Connection) -> Optional[int]:
    mod_id = enqueue_item(item, conn)
    if not mod_id:
        return None
    mid = send_preview(conn, mod_id)
    if not mid:
        logger.error("[PREVIEW_FAIL] id=%d", mod_id)
        return None
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
    conn.execute(
        "INSERT INTO moderation_actions (post_id, user_id, action, payload, created_at) VALUES(?,?,?, ?, strftime('%s','now'))",
        (mod_id, moderator_id, "approve", json.dumps({"override": bool(text_override)})),
    )
    conn.execute(
        "UPDATE moderation_messages SET state = ?, updated_at = strftime('%s','now') WHERE post_id = ?",
        (APPROVED, mod_id),
    )
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
    if cur.rowcount > 0:
        conn.execute(
            "INSERT INTO moderation_actions (post_id, user_id, action, payload, created_at) VALUES(?,?,?, ?, strftime('%s','now'))",
            (mod_id, moderator_id, "reject", json.dumps({"comment": comment})),
        )
        conn.execute(
            "UPDATE moderation_messages SET state = ?, updated_at = strftime('%s','now') WHERE post_id = ?",
            (REJECTED, mod_id),
        )
        conn.commit()
    return cur.rowcount > 0


def snooze(conn: sqlite3.Connection, mod_id: int, moderator_id: int, minutes: int) -> bool:
    """Temporarily skip item for a number of minutes."""
    if not is_moderator(moderator_id):
        return False
    resume = int(time.time()) + minutes * 60
    cur = conn.execute(
        "UPDATE moderation_queue SET status = ?, resume_at = ?, reviewed_at = strftime('%s','now'), moderator_user_id = ? WHERE id = ? AND status IN ('PENDING_REVIEW','SNOOZED')",
        (SNOOZED, resume, moderator_id, mod_id),
    )
    conn.commit()
    if cur.rowcount > 0:
        conn.execute(
            "INSERT INTO moderation_actions (post_id, user_id, action, payload, created_at) VALUES(?,?,?, ?, strftime('%s','now'))",
            (mod_id, moderator_id, "snooze", json.dumps({"minutes": minutes})),
        )
        conn.execute(
            "UPDATE moderation_messages SET state = ?, updated_at = strftime('%s','now') WHERE post_id = ?",
            (SNOOZED, mod_id),
        )
        conn.commit()
    return cur.rowcount > 0


def start_edit(
    conn: sqlite3.Connection, mod_id: int, moderator_id: int, field: str
) -> bool:
    """Begin editing a field (title, text, tags, reject)."""
    if not is_moderator(moderator_id):
        return False
    conn.execute(
        "INSERT OR REPLACE INTO editor_state(user_id, item_id, field, started_at) VALUES (?,?,?,strftime('%s','now'))",
        (moderator_id, mod_id, field),
    )
    conn.execute(
        "INSERT INTO moderation_actions (post_id, user_id, action, payload, created_at) VALUES(?,?,?, ?, strftime('%s','now'))",
        (mod_id, moderator_id, f"start_edit_{field}", json.dumps({})),
    )
    conn.commit()
    return True


def cancel_edit(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute("DELETE FROM editor_state WHERE user_id = ?", (user_id,))
    conn.commit()


def apply_edit_message(conn: sqlite3.Connection, user_id: int, text: str) -> bool:
    cur = conn.execute(
        "SELECT item_id, field FROM editor_state WHERE user_id = ?", (user_id,)
    )
    row = cur.fetchone()
    if not row:
        return False
    mod_id = int(row["item_id"])
    field = row["field"] or "content"
    if field == "title":
        conn.execute(
            "UPDATE moderation_queue SET title = ?, status = ? WHERE id = ?",
            (text, PENDING_REVIEW, mod_id),
        )
    elif field == "tags":
        conn.execute(
            "UPDATE moderation_queue SET tags = ?, status = ? WHERE id = ?",
            (text, PENDING_REVIEW, mod_id),
        )
    elif field == "reject":
        conn.execute(
            "UPDATE moderation_queue SET status = ?, reviewed_at = strftime('%s','now'), moderator_comment = ? WHERE id = ?",
            (REJECTED, text, mod_id),
        )
    else:
        conn.execute(
            "UPDATE moderation_queue SET content = ?, status = ? WHERE id = ?",
            (text, PENDING_REVIEW, mod_id),
        )
    conn.execute(
        "INSERT INTO moderation_actions (post_id, user_id, action, payload, created_at) VALUES(?,?,?, ?, strftime('%s','now'))",
        (mod_id, user_id, f"apply_{field}", json.dumps({"text": text})),
    )
    conn.execute("DELETE FROM editor_state WHERE user_id = ?", (user_id,))
    conn.commit()
    send_preview(conn, mod_id)
    return True


def handle_callback(conn: sqlite3.Connection, update: dict) -> Optional[str]:
    cb = update.get("callback_query") or {}
    data = cb.get("data", "")
    user_id = int(cb.get("from", {}).get("id", 0))
    if not (data.startswith("mod:") or data.startswith("m:")):
        return None
    parts = data.split(":")
    if len(parts) < 3:
        return None
    _, sid, action, *rest = parts
    try:
        mod_id = int(sid)
    except Exception:
        return None
    extra = rest[0] if rest else None
    if not is_moderator(user_id):
        logger.warning("unauthorized callback", extra={"user_id": user_id, "action": action})
        return "forbidden"
    result: Optional[str] = None
    if action in {"approve", "ok"}:
        if approve(conn, mod_id, user_id):
            result = "approve"
    elif action in {"reject", "rej"}:
        start_edit(conn, mod_id, user_id, "reject")
        result = "reject"
    elif action in {"snooze", "sz"}:
        minutes = int(extra or 0) if extra else 0
        if minutes <= 0:
            minutes = int(getattr(config, "SNOOZE_MINUTES", 0) or 0)
        if minutes <= 0:
            minutes = 60
        snooze(conn, mod_id, user_id, minutes)
        result = "snooze"
    elif action in {"edit", "edit_text", "et"}:
        start_edit(conn, mod_id, user_id, "content")
        result = "edit_text"
    elif action in {"edit_title", "eh"}:
        start_edit(conn, mod_id, user_id, "title")
        result = "edit_title"
    elif action in {"edit_tags", "tg"}:
        start_edit(conn, mod_id, user_id, "tags")
        result = "edit_tags"
    logger.info(
        "callback", extra={"post_id": mod_id, "action": action, "from_id": user_id}
    )
    return result


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

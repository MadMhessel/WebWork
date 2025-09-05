import logging
from typing import Optional, Dict, Any, List
import requests
import sqlite3

from . import config, publisher, dedup, images, rewrite

logger = logging.getLogger(__name__)

# ----------- Status constants -----------
PENDING_REVIEW = "pending"
REJECTED = "rejected"
SNOOZED = "snoozed"
APPROVED = "approved"
PUBLISHED = "published"

# ---------------- DB helpers ----------------

def _get_state(conn: sqlite3.Connection, key: str) -> Optional[str]:
    cur = conn.execute("SELECT value FROM bot_state WHERE key = ?", (key,))
    row = cur.fetchone()
    return row["value"] if row else None

def _set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO bot_state(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    conn.commit()

def already_pending(conn: sqlite3.Connection, url: str) -> Optional[int]:
    cur = conn.execute(
        "SELECT id FROM moderation_queue WHERE url = ? AND status = ?",
        (url, PENDING_REVIEW),
    )
    row = cur.fetchone()
    return int(row["id"]) if row else None

def insert_pending(conn: sqlite3.Connection, item: Dict[str, str]) -> int:
    cur = conn.execute("""
        INSERT OR IGNORE INTO moderation_queue (source, guid, url, title, content, published_at, image_url, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
        (
            item.get("source",""),
            item.get("guid"),
            item.get("url",""),
            item.get("title",""),
            item.get("content",""),
            item.get("published_at",""),
            item.get("image_url"),
        )
    )
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO moderation_queue (source, guid, url, title, content, published_at, image_url, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
        """,
        (
            item.get("source", ""),
            item.get("guid"),
            item.get("url", ""),
            item.get("title", ""),
            item.get("content", ""),
            item.get("published_at", ""),
            item.get("image_url", ""),
        ),
    )
def insert_pending(conn: sqlite3.Connection, item: Dict[str, str]) -> int:
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO moderation_queue (source, guid, url, title, content, published_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item.get("source", ""),
            item.get("guid"),
            item.get("url", ""),
            item.get("title", ""),
            item.get("content", ""),
            item.get("published_at", ""),
            PENDING_REVIEW,
        ),
    )
    if cur.rowcount == 0:
        # запись уже есть (скорее всего из-за UNIQUE(url)); вернём существующий id
        cur2 = conn.execute("SELECT id FROM moderation_queue WHERE url = ?", (item.get("url",""),))
        row = cur2.fetchone()
        return int(row["id"])
    conn.commit()
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

def set_status(conn: sqlite3.Connection, mod_id: int, status: str) -> None:
    conn.execute("UPDATE moderation_queue SET status = ? WHERE id = ?", (status, mod_id))

def set_tg_message_id(conn: sqlite3.Connection, mod_id: int, message_id: str) -> None:
    conn.execute("UPDATE moderation_queue SET tg_message_id = ? WHERE id = ?", (message_id, mod_id))
    conn.commit()

def set_channel_message_id(conn: sqlite3.Connection, mod_id: int, message_id: str) -> None:
    conn.execute(
        "UPDATE moderation_queue SET channel_message_id = ? WHERE id = ?",
        (message_id, mod_id),
    )
    conn.commit()
def set_tg_message_id(conn: sqlite3.Connection, mod_id: int, message_id: str) -> None:
    conn.execute("UPDATE moderation_queue SET tg_message_id = ? WHERE id = ?", (message_id, mod_id))

def get_item(conn: sqlite3.Connection, mod_id: int) -> Optional[Dict[str, Any]]:
    cur = conn.execute("SELECT * FROM moderation_queue WHERE id = ?", (mod_id,))
    row = cur.fetchone()
    return dict(row) if row else None

def enqueue_item(item: Dict[str, str], conn: sqlite3.Connection) -> Optional[int]:
    """Place item into moderation queue. Returns mod_id or None."""
    if not config.ENABLE_MODERATION:
        return None

def enqueue_item(item: Dict[str, str], conn: sqlite3.Connection) -> Optional[int]:
    """Поместить новость в очередь модерации со статусом ``pending``."""

    if not config.ENABLE_MODERATION:
        return None

    existed = already_pending(conn, item.get("url", ""))
    if existed:
        logger.info("[QUEUE] уже в модерации (id=%d): %s", existed, item.get("title", "")[:140])
        return existed
    mod_id = insert_pending(conn, item)
    logger.info("[QUEUED] id=%d | %s", mod_id, (item.get("title") or "")[:140])
    return mod_id


def send_preview(conn: sqlite3.Connection, mod_id: int) -> Optional[str]:
    """Send moderation preview to all moderators. Returns message_id of first send."""
    it = get_item(conn, mod_id)
    if not it:
        logger.error("[QUEUE] item id=%d not found for preview", mod_id)
        return None
    title = it.get("title", "") or ""
    body = it.get("content", "") or ""
    url = it.get("url", "") or ""
    header = f"Предмодерация #{mod_id}"
    mid_saved: Optional[str] = None
    moderators: List[str] = list(getattr(config, "MODERATOR_IDS", []) or [])
    if not moderators:
        admin_chat = (getattr(config, "ADMIN_CHAT_ID", "") or "").strip()
        if admin_chat:
            moderators = [admin_chat]
    for chat_id in moderators:
        mid = publisher.send_moderation_preview(chat_id, header, title, body, url, mod_id, cfg=config)
        if mid and not mid_saved:
            mid_saved = mid
    if mid_saved:
        with conn:
            set_tg_message_id(conn, mod_id, mid_saved)
    return mid_saved


def enqueue_and_notify(item: Dict[str, str], conn: sqlite3.Connection) -> Optional[int]:
    """Backward-compatible helper: enqueue item and send preview."""
    mod_id = enqueue_item(item, conn)
    if mod_id is None:
        return None
    send_preview(conn, mod_id)

    try:
        mod_id = insert_pending(conn, item)
        logger.info("[QUEUED] id=%d | %s", mod_id, (item.get("title", "") or "")[:140])
        return mod_id
    except Exception as ex:  # pragma: no cover
        logger.exception("Ошибка постановки в очередь модерации: %s", ex)
        return None


def send_preview(item: Dict[str, str], mod_id: int, conn: sqlite3.Connection) -> Optional[str]:
    """Отправить предпросмотр модератору для записи из очереди."""

    if not config.ENABLE_MODERATION:
        return None

    admin_chat = (getattr(config, "ADMIN_CHAT_ID", "") or "").strip()
    if not admin_chat:
        logger.error("ADMIN_CHAT_ID не задан — модерация невозможна.")
        return None

    # не ставим дубль в pending
    existed = already_pending(conn, item.get("url",""))
    if existed:
        logger.info("[QUEUE] уже в модерации (id=%d): %s", existed, item.get("title","")[:140])
        return existed

    item = rewrite.maybe_rewrite_item(item, config)
    candidates = images.extract_candidates(item)
    best = images.pick_best(candidates)
    tg_file_id = images.ensure_tg_file_id(best.url) if best else None
    item["image_url"] = tg_file_id or ""

    mod_id = insert_pending(conn, item)
    title = item.get("title","") or ""
    body  = item.get("content","") or ""
    url   = item.get("url","") or ""
    images = item.get("image_file_ids") or item.get("tg_file_ids") or item.get("image_tg_file_ids") or []
    if isinstance(images, str):
        images = [images]
    header = f"Предмодерация #{mod_id}"
    mid = publisher.send_moderation_preview(admin_chat, header, title, body, url, mod_id, images=images, cfg=config)
    title = item.get("title", "") or ""
    body = item.get("content", "") or ""
    url = item.get("url", "") or ""
    header = f"Предмодерация #{mod_id}"

    mid = publisher.send_moderation_preview(admin_chat, header, title, body, url, mod_id, cfg=config)
    if mid:
        set_tg_message_id(conn, mod_id, mid)
        return mid
    logger.error("Не удалось отправить предпросмотр модератору (id=%d).", mod_id)
    return None


def enqueue_and_notify(item: Dict[str, str], conn: sqlite3.Connection) -> Optional[int]:
    """Совместная функция для обратной совместимости."""
    mod_id = enqueue_item(item, conn)
    if mod_id:
        send_preview(item, mod_id, conn)
    return mod_id


# --------------- Updates processing ----------------

def _tg_get_updates(offset: Optional[int] = None, timeout: int = 20) -> Optional[Dict[str, Any]]:
    if publisher._ensure_client() is False:
        return None
    url = f"{publisher._client_base_url}/getUpdates"  # type: ignore
    params = {"timeout": str(timeout), "allowed_updates": '["message","callback_query"]'}
    if offset is not None:
        params["offset"] = str(offset)
    try:
        r = requests.get(url, params=params, timeout=timeout+10)
        j = r.json()
        if not j.get("ok"):
            logger.error("getUpdates ok=false: %s", r.text)
            return None
        return j
    except Exception as ex:
        logger.exception("Ошибка getUpdates: %s", ex)
        return None


def handle_callback(cb: Dict[str, Any], conn: sqlite3.Connection) -> None:
    cq_id = str(cb.get("id"))
    from_user = cb.get("from") or {}
    user_id = str(from_user.get("id"))
    data = str(cb.get("data") or "")
    msg = cb.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id"))
    message_id = str(msg.get("message_id"))

    if config.MODERATOR_IDS and user_id not in config.MODERATOR_IDS:
        if cq_id:
            publisher.answer_callback_query(cq_id, text="Нет доступа", show_alert=True)
        logger.warning("Unauthorized callback from %s", user_id)
        return

    if not data or ":" not in data:
        if cq_id:
            publisher.answer_callback_query(cq_id, text="Некорректные данные.", show_alert=False)
        return
    action, mod_id_str = data.split(":", 1)
    try:
        mod_id = int(mod_id_str)
    except ValueError:
        if cq_id:
            publisher.answer_callback_query(cq_id, text="Некорректный ID.", show_alert=False)
        return

    it = get_item(conn, mod_id)
    if not it:
        if cq_id:
            publisher.answer_callback_query(cq_id, text="Запись не найдена.", show_alert=True)
        return

    title = it.get("title","") or ""
    url   = it.get("url","") or ""
    body  = it.get("content","") or ""
    source= it.get("source","") or ""

    if action == "approve":
        # Публикуем в канал
        ok = publisher.publish_message(
            chat_id=config.CHANNEL_ID,
            title=title,
            body=body,
            url=url,
            image_url=it.get("image_url"),
            cfg=config,
        )
        channel_mid = publisher.publish_to_channel(mod_id)
        if channel_mid:
            # Запись в антидубль и смена статуса
            dedup.mark_published(
                url=url,
                guid=it.get("guid"),
                title=title,
                published_at=it.get("published_at") or "",
                source=source,
                image_url=it.get("image_url"),
                db_conn=conn,
            )
            set_status(conn, mod_id, "approved")
            set_channel_message_id(conn, mod_id, channel_mid)
            publisher.answer_callback_query(cq_id, text="Опубликовано ✅", show_alert=False)
            publisher.edit_moderation_message(
                chat_id,
                message_id,
                f"✅ Одобрено и отправлено в канал.\n\n<b>{html_escape(title)}</b>\n{html_escape(url)}",
                cfg=config,
            )
        else:
            publisher.answer_callback_query(cq_id, text="Ошибка отправки в канал.", show_alert=True)
    title = it.get("title", "") or ""
    url = it.get("url", "") or ""
    body = it.get("content", "") or ""
    source = it.get("source", "") or ""

    if action == "publish":
        # Публикуем в канал
        ok = publisher.publish_message(
            chat_id=config.CHANNEL_ID,
            title=title,
            body=body,
            url=url,
            cfg=config,
        )
        if ok:
            # Запись в антидубль и смена статуса
            from . import db as dbmod
            dedup.mark_published(
                url=url,
                guid=it.get("guid"),
                title=title,
                published_at=it.get("published_at") or "",
                source=source,
                image_url=it.get("image_url"),
                db_conn=conn,
            )
            set_status(conn, mod_id, "approved")
            publisher.answer_callback_query(cq_id, text="Опубликовано ✅", show_alert=False)
            publisher.edit_moderation_message(chat_id, message_id, f"✅ Одобрено и отправлено в канал.\n\n<b>{html_escape(title)}</b>\n{html_escape(url)}", cfg=config)
        else:
            publisher.answer_callback_query(cq_id, text="Ошибка отправки в канал.", show_alert=True)
    elif action == "reject":
        set_status(conn, mod_id, "rejected")
        publisher.answer_callback_query(cq_id, text="Отклонено ❌", show_alert=False)
        publisher.edit_moderation_message(chat_id, message_id, f"❌ Отклонено.\n\n<b>{html_escape(title)}</b>\n{html_escape(url)}", cfg=config)
    elif action == "snooze":
        publisher.answer_callback_query(cq_id, text="Отложено ⏰", show_alert=False)
        publisher.edit_moderation_message(chat_id, message_id, f"⏰ Отложено.\n\n<b>{html_escape(title)}</b>\n{html_escape(url)}", cfg=config)
    elif action == "edit":
        publisher.answer_callback_query(cq_id, text="Редактирование не поддерживается", show_alert=True)
    else:
        publisher.answer_callback_query(cq_id, text="Неизвестное действие.", show_alert=False)
    if action == "approve":
        with conn:
            set_status(conn, mod_id, APPROVED)
            ok = publisher.publish_message(
                chat_id=config.CHANNEL_ID,
                title=title,
                body=body,
                url=url,
                cfg=config,
            )
            if ok:
                dedup.mark_published(
                    url=url,
                    guid=it.get("guid"),
                    title=title,
                    published_at=it.get("published_at") or "",
                    source=source,
                    image_url=it.get("image_url"),
                    db_conn=conn,
                )
                set_status(conn, mod_id, PUBLISHED)
                if cq_id:
                    publisher.answer_callback_query(cq_id, text="Опубликовано ✅", show_alert=False)
                if message_id and chat_id:
                    publisher.edit_moderation_message(
                        chat_id,
                        message_id,
                        f"✅ Одобрено и отправлено в канал.\n\n<b>{html_escape(title)}</b>\n{html_escape(url)}",
                        cfg=config,
                    )
                logger.info("[PUBLISHED] id=%d by %s", mod_id, user_id)
            else:
                if cq_id:
                    publisher.answer_callback_query(cq_id, text="Ошибка отправки в канал.", show_alert=True)
                logger.error("Publish failed for id=%d", mod_id)
    elif action == "reject":
        with conn:
            set_status(conn, mod_id, REJECTED)
        if cq_id:
            publisher.answer_callback_query(cq_id, text="Отклонено ❌", show_alert=False)
        if message_id and chat_id:
            publisher.edit_moderation_message(
                chat_id,
                message_id,
                f"❌ Отклонено.\n\n<b>{html_escape(title)}</b>\n{html_escape(url)}",
                cfg=config,
            )
        logger.info("[REJECTED] id=%d by %s", mod_id, user_id)
    elif action == "snooze":
        with conn:
            set_status(conn, mod_id, SNOOZED)
        if cq_id:
            publisher.answer_callback_query(cq_id, text="Отложено 🕐", show_alert=False)
        if message_id and chat_id:
            publisher.edit_moderation_message(
                chat_id,
                message_id,
                f"🕐 Отложено.\n\n<b>{html_escape(title)}</b>\n{html_escape(url)}",
                cfg=config,
            )
        logger.info("[SNOOZED] id=%d by %s", mod_id, user_id)
    elif action == "edit":
        if cq_id:
            publisher.answer_callback_query(cq_id, text="Режим редактирования не поддерживается", show_alert=False)
        logger.info("[EDIT] request for id=%d by %s", mod_id, user_id)
    else:
        if cq_id:
            publisher.answer_callback_query(cq_id, text="Неизвестное действие.", show_alert=False)


def handle_message(msg: Dict[str, Any], conn: sqlite3.Connection) -> None:
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id"))
    from_user = msg.get("from") or {}
    user_id = str(from_user.get("id"))
    text = (msg.get("text") or "").strip()
    if not text.startswith("/"):
        return
    if config.MODERATOR_IDS and user_id not in config.MODERATOR_IDS:
        publisher.send_message(chat_id, "Нет доступа.")
        logger.warning("Unauthorized command from %s: %s", user_id, text)
        return
    parts = text.split()
    cmd = parts[0].lower()
    if cmd == "/queue":
        cur = conn.execute(
            "SELECT id, title FROM moderation_queue WHERE status = ? ORDER BY id",
            (PENDING_REVIEW,),
        )
        rows = cur.fetchall()
        if rows:
            lines = [f"{r['id']}: {r['title'][:60]}" for r in rows]
            resp = "Очередь:\n" + "\n".join(lines)
        else:
            resp = "Очередь пуста."
        publisher.send_message(chat_id, resp)
    elif cmd == "/approve" and len(parts) >= 2:
        try:
            mod_id = int(parts[1])
        except ValueError:
            publisher.send_message(chat_id, "Некорректный ID.")
            return
        # Use callback handler logic without callback query
        fake_cb = {"id": "", "data": f"approve:{mod_id}", "message": {"chat": {"id": chat_id}, "message_id": ""}, "from": {"id": user_id}}
        handle_callback(fake_cb, conn)
        publisher.send_message(chat_id, f"Запись {mod_id} обработана.")
    elif cmd == "/reject" and len(parts) >= 2:
        try:
            mod_id = int(parts[1])
        except ValueError:
            publisher.send_message(chat_id, "Некорректный ID.")
            return
        reason = " ".join(parts[2:]).strip()
        with conn:
            set_status(conn, mod_id, REJECTED)
        publisher.send_message(
            chat_id,
            f"Запись {mod_id} отклонена." + (f" Причина: {reason}" if reason else ""),
        )
        logger.info("[REJECTED] id=%d by %s reason=%s", mod_id, user_id, reason)
    elif cmd == "/stats":
        cur = conn.execute("SELECT status, COUNT(*) as c FROM moderation_queue GROUP BY status")
        rows = cur.fetchall()
        lines = [f"{r['status']}: {r['c']}" for r in rows]
        resp = "Статистика:\n" + "\n".join(lines)
        publisher.send_message(chat_id, resp)
    else:
        publisher.send_message(chat_id, "Неизвестная команда.")


def process_updates_once(conn: sqlite3.Connection, *, timeout: int = 20) -> None:
    """
    Обрабатывает callback_query из getUpdates один раз (с long-poll до timeout).
    """
    last = _get_state(conn, "last_update_id")
    offset = int(last) + 1 if last is not None else None
    j = _tg_get_updates(offset=offset, timeout=timeout)
    if not j:
        return
    results = j.get("result") or []
    max_update_id = None
    for upd in results:
        upd_id = upd.get("update_id")
        if max_update_id is None or upd_id > max_update_id:
            max_update_id = upd_id
        if "callback_query" in upd:
            try:
                handle_callback(upd["callback_query"], conn)
            except Exception as ex:
                logger.exception("Ошибка обработки callback_query: %s", ex)
        elif "message" in upd:
            try:
                handle_message(upd["message"], conn)
            except Exception as ex:
                logger.exception("Ошибка обработки message: %s", ex)
    if max_update_id is not None:
        _set_state(conn, "last_update_id", str(max_update_id))


# --------------- Utils ---------------

def html_escape(s: str) -> str:
    import html as _html
    return _html.escape(s or "", quote=True)

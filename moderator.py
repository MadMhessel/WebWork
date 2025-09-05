import logging
from typing import Optional, Dict, Any
import requests
import sqlite3

from . import config, publisher, dedup

logger = logging.getLogger(__name__)

# ---------------- DB helpers ----------------

def _get_state(conn: sqlite3.Connection, key: str) -> Optional[str]:
    cur = conn.execute("SELECT value FROM bot_state WHERE key = ?", (key,))
    row = cur.fetchone()
    return row["value"] if row else None

def _set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO bot_state(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    conn.commit()

def already_pending(conn: sqlite3.Connection, url: str) -> Optional[int]:
    cur = conn.execute("SELECT id FROM moderation_queue WHERE url = ? AND status = 'pending'", (url,))
    row = cur.fetchone()
    return int(row["id"]) if row else None

def insert_pending(conn: sqlite3.Connection, item: Dict[str, str]) -> int:
    cur = conn.execute("""
        INSERT OR IGNORE INTO moderation_queue (source, guid, url, title, content, published_at, status)
        VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
        (item.get("source",""), item.get("guid"), item.get("url",""), item.get("title",""), item.get("content",""), item.get("published_at",""))
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
    conn.commit()

def set_tg_message_id(conn: sqlite3.Connection, mod_id: int, message_id: str) -> None:
    conn.execute("UPDATE moderation_queue SET tg_message_id = ? WHERE id = ?", (message_id, mod_id))
    conn.commit()

def get_item(conn: sqlite3.Connection, mod_id: int) -> Optional[Dict[str, Any]]:
    cur = conn.execute("SELECT * FROM moderation_queue WHERE id = ?", (mod_id,))
    row = cur.fetchone()
    return dict(row) if row else None


# --------------- Moderation sending ----------------

def enqueue_and_notify(item: Dict[str, str], conn: sqlite3.Connection) -> Optional[int]:
    """
    Ставит новость в очередь модерации (если ещё не стоит) и отправляет предпросмотр модератору.
    Возвращает mod_id или None при ошибке/отключенной модерации.
    """
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

    mod_id = insert_pending(conn, item)
    title = item.get("title","") or ""
    body  = item.get("content","") or ""
    url   = item.get("url","") or ""
    images = item.get("image_file_ids") or item.get("tg_file_ids") or item.get("image_tg_file_ids") or []
    if isinstance(images, str):
        images = [images]
    header = f"Предмодерация #{mod_id}"
    mid = publisher.send_moderation_preview(admin_chat, header, title, body, url, mod_id, images=images, cfg=config)
    if mid:
        set_tg_message_id(conn, mod_id, mid)
        logger.info("[QUEUED] id=%d | %s", mod_id, title[:140])
        return mod_id
    else:
        logger.error("Не удалось отправить предпросмотр модератору (id=%d).", mod_id)
        return mod_id  # оставим в очереди pending, можно будет переслать позже


# --------------- Updates processing ----------------

def _tg_get_updates(offset: Optional[int] = None, timeout: int = 20) -> Optional[Dict[str, Any]]:
    if publisher._ensure_client() is False:
        return None
    url = f"{publisher._client_base_url}/getUpdates"  # type: ignore
    params = {"timeout": str(timeout), "allowed_updates": '["callback_query"]'}
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


def _handle_callback_query(cb: Dict[str, Any], conn: sqlite3.Connection) -> None:
    cq_id = str(cb.get("id"))
    data = str(cb.get("data") or "")
    msg = cb.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id"))
    message_id = str(msg.get("message_id"))

    if not data or ":" not in data:
        publisher.answer_callback_query(cq_id, text="Некорректные данные.", show_alert=False)
        return
    action, mod_id_str = data.split(":", 1)
    try:
        mod_id = int(mod_id_str)
    except ValueError:
        publisher.answer_callback_query(cq_id, text="Некорректный ID.", show_alert=False)
        return

    it = get_item(conn, mod_id)
    if not it:
        publisher.answer_callback_query(cq_id, text="Запись не найдена.", show_alert=True)
        return

    title = it.get("title","") or ""
    url   = it.get("url","") or ""
    body  = it.get("content","") or ""
    source= it.get("source","") or ""

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
                _handle_callback_query(upd["callback_query"], conn)
            except Exception as ex:
                logger.exception("Ошибка обработки callback_query: %s", ex)
    if max_update_id is not None:
        _set_state(conn, "last_update_id", str(max_update_id))


# --------------- Utils ---------------

def html_escape(s: str) -> str:
    import html as _html
    return _html.escape(s or "", quote=True)

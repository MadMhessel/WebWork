import logging
import time
from typing import Optional

try:
    from . import config, http_client, moderator, publisher, db
except ImportError:  # pragma: no cover
    import config, http_client, moderator, publisher, db  # type: ignore

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"


def run(stop_event) -> None:
    session = http_client.get_session()
    offset = 0
    conn = db.connect()
    while not stop_event.is_set():
        try:
            url = f"{API_BASE}/bot{config.BOT_TOKEN}/getUpdates"
            params = {"timeout": 30, "offset": offset}
            resp = session.get(
                url,
                params=params,
                timeout=(config.HTTP_TIMEOUT_CONNECT, config.HTTP_TIMEOUT_READ),
            )
            resp.raise_for_status()
            data = resp.json()
            for upd in data.get("result", []):
                offset = max(offset, upd.get("update_id", 0) + 1)
                _handle_update(conn, session, upd)
        except Exception as ex:
            logger.debug("update loop error: %s", ex)
            time.sleep(5)
    try:
        conn.close()
    except Exception:
        pass


def _handle_update(conn, session, update: dict) -> None:
    if update.get("callback_query"):
        cb = update["callback_query"]
        user_id = int(cb.get("from", {}).get("id", 0))
        data = cb.get("data", "")
        if not moderator.is_moderator(user_id):
            publisher.send_message(str(user_id), "Нет доступа", cfg=config)
            return
        action = ""
        if data.startswith("mod:"):
            parts = data.split(":")
            if len(parts) >= 3:
                action = parts[2]
        moderator.handle_callback(conn, update)
        if action == "edit":
            publisher.send_message(
                str(user_id), "Пришлите текст одним сообщением или /cancel", cfg=config
            )
        return
    msg = update.get("message")
    if not msg:
        return
    user_id = int(msg.get("from", {}).get("id", 0))
    text = msg.get("text", "")
    chat_id = msg.get("chat", {}).get("id")
    if text is None:
        return
    if not moderator.is_moderator(user_id):
        if text.startswith("/"):
            publisher.send_message(str(user_id), "Нет доступа", cfg=config)
        return
    if text.startswith("/queue"):
        parts = text.strip().split()
        page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
        moderator.cmd_queue(conn, chat_id, page)
    elif text.startswith("/approve"):
        parts = text.strip().split()
        if len(parts) >= 2 and parts[1].isdigit():
            moderator.cmd_approve(conn, int(parts[1]), user_id)
    elif text.startswith("/reject"):
        parts = text.strip().split(maxsplit=2)
        if len(parts) >= 2 and parts[1].isdigit():
            reason = parts[2] if len(parts) > 2 else None
            moderator.cmd_reject(conn, int(parts[1]), user_id, reason)
    elif text.startswith("/stats"):
        moderator.cmd_stats(conn, chat_id)
    elif text.startswith("/cancel"):
        moderator.cancel_edit(conn, user_id)
        publisher.send_message(str(user_id), "Отменено", cfg=config)
    else:
        if moderator.apply_edit_message(conn, user_id, text):
            publisher.send_message(str(user_id), "Обновлено", cfg=config)

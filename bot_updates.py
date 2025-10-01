# import-shim for flat layout
if __name__ == "__main__" or __package__ is None:
    import os, sys
    sys.path.insert(0, os.path.dirname(__file__))

import config
import db
import http_client
import moderator
import publisher

import time

from logging_setup import get_logger

logger = get_logger(__name__)

API_BASE = "https://api.telegram.org"


def run(stop_event) -> None:
    session = http_client.get_session()
    offset = 0
    conn = db.connect()
    while not stop_event.is_set():
        try:
            url = f"{API_BASE}/bot{config.BOT_TOKEN}/getUpdates"
            params = {"timeout": config.TELEGRAM_LONG_POLL, "offset": offset}
            resp = session.get(
                url,
                params=params,
                timeout=(
                    config.HTTP_TIMEOUT_CONNECT,
                    config.TELEGRAM_LONG_POLL + 10,
                ),
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
    msg = update.get("message")
    if not msg:
        return
    user_id = int(msg.get("from", {}).get("id", 0))
    text = msg.get("text", "")
    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    sender_chat = msg.get("sender_chat")
    if text is None:
        return
    allowed = moderator.is_moderator(user_id)
    if not allowed and sender_chat:
        sender_chat_id = sender_chat.get("id")
        try:
            if sender_chat_id is not None and moderator.is_moderator(int(sender_chat_id)):
                allowed = True
        except (TypeError, ValueError):
            pass
        if not allowed and moderator.is_sender_authorized(sender_chat):
            allowed = True
    if not allowed:
        if text.startswith("/"):
            target = user_id or chat_id
            if target:
                publisher.send_message(str(target), "Нет доступа", cfg=config)
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

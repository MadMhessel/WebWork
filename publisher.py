import html
import json
import logging
import time
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple, Union
import sqlite3

import requests

try:
    from . import config, db, rewrite, http_client, images
    from .utils import shorten_url
except ImportError:  # pragma: no cover
    import config, db, rewrite, http_client, images  # type: ignore
    from utils import shorten_url  # type: ignore

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org"
_client_base_url: Optional[str] = None


# ---------------------------------------------------------------------------
# Client helpers
# ---------------------------------------------------------------------------

def init_telegram_client(token: Optional[str] = None) -> None:
    """Initialize base URL for Telegram Bot API."""
    global _client_base_url
    token = (token or getattr(config, "BOT_TOKEN", "").strip())
    if not token:
        logger.warning("BOT_TOKEN пуст — отправка в Telegram отключена.")
        _client_base_url = None
        return
    _client_base_url = f"{_API_BASE}/bot{token}"


def _ensure_client() -> bool:
    if _client_base_url is None:
        init_telegram_client()
    return _client_base_url is not None


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

_MD_V2_RESERVED = "_*[]()~`>#+-=|{}.!\\"

def _escape_markdown_v2(text: str) -> str:
    return "".join(f"\\{ch}" if ch in _MD_V2_RESERVED else ch for ch in text or "")


def _escape_html(text: str) -> str:
    return html.escape(text or "", quote=True)


def _build_message(title: str, body: str, url: str, parse_mode: str) -> str:
    if parse_mode == "MARKDOWNV2":
        t = _escape_markdown_v2(title)
        b = _escape_markdown_v2(body)
        u = _escape_markdown_v2(url)
        return f"*{t}*\n\n{b}\n\n[Подробнее]({u})".strip()
    et = _escape_html(title)
    eb = _escape_html(body)
    eu = _escape_html(url)
    return f"<b>{et}</b>\n\n{eb}\n\nПодробнее: <a href=\"{eu}\">{eu}</a>".strip()


def _smart_trim(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rstrip()
    pos = cut.rfind(" ")
    return (cut[:pos] if pos > 0 else cut) + "…"


def compose_preview(title: str, body: str, url: str, parse_mode: str) -> tuple[str, Optional[str]]:
    full = _build_message(title, body, url, parse_mode)
    caption_limit = int(getattr(config, "CAPTION_LIMIT", 1024))
    msg_limit = int(getattr(config, "TELEGRAM_MESSAGE_LIMIT", 4096))
    if len(full) <= caption_limit:
        return full, None
    caption = _smart_trim(full, caption_limit)
    long_text = _smart_trim(full, msg_limit)
    return caption, long_text


# ---------------------------------------------------------------------------
# Telegram HTTP helpers
# ---------------------------------------------------------------------------

def _api_post(method: str, payload: Dict[str, Any], files: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if not _ensure_client():
        return None
    url = f"{_client_base_url}/{method}"
    try:
        r = requests.post(url, data=payload, files=files, timeout=30)
        if r.status_code != 200:
            logger.error("Ошибка HTTP %s: %s %s", method, r.status_code, r.text)
            return None
        j = r.json()
        if not j.get("ok"):
            logger.error("Telegram %s ok=false: %s", method, r.text)
            return None
        return j
    except Exception as ex:  # pragma: no cover
        logger.exception("Исключение при вызове Telegram %s: %s", method, ex)
        return None


def _send_text(chat_id: str, text: str, parse_mode: str, reply_markup: Optional[dict] = None) -> Optional[str]:
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": "true" if getattr(config, "TELEGRAM_DISABLE_WEB_PAGE_PREVIEW", False) else "false",
    }
    if reply_markup is not None:
        payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    j = _api_post("sendMessage", payload)
    if not j:
        return None
    return str(j.get("result", {}).get("message_id"))


def _send_photo(
    chat_id: str,
    photo: Union[BytesIO, str],
    caption: str,
    parse_mode: str,
    mime: Optional[str] = None,
    reply_markup: Optional[dict] = None,
) -> Optional[Tuple[str, Optional[str]]]:
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "caption": caption,
        "parse_mode": parse_mode,
    }
    if reply_markup is not None:
        payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    files = None
    if isinstance(photo, BytesIO):
        if not mime:
            raise ValueError("mime required when uploading BytesIO")
        files = {"photo": ("image", photo, mime)}
    else:
        payload["photo"] = photo
    j = _api_post("sendPhoto", payload, files=files)
    if not j:
        return None
    res = j.get("result", {})
    fid = None
    try:
        fid = res.get("photo", [{}])[-1].get("file_id")
    except Exception:
        fid = None
    return str(res.get("message_id")), fid


# ---------------------------------------------------------------------------
# Public helpers used in tests and pipeline
# ---------------------------------------------------------------------------

def send_message(chat_id: str, text: str, cfg=config) -> Optional[str]:
    parse_mode = (cfg.TELEGRAM_PARSE_MODE or getattr(cfg, "PARSE_MODE", "HTML")).upper()
    return _send_text(chat_id, text, parse_mode)


def _download_image(url: str, cfg=config) -> Optional[Tuple[BytesIO, str]]:
    timeout = (config.HTTP_TIMEOUT_CONNECT, config.HTTP_TIMEOUT_READ)
    max_bytes = int(getattr(cfg, "IMAGE_MAX_BYTES", 5 * 1024 * 1024))
    session = http_client.get_session()
    try:
        with session.get(url, timeout=timeout, stream=True) as r:
            if r.status_code != 200:
                return None
            ctype = (r.headers.get("Content-Type") or "").split(";")[0]
            if not ctype.startswith("image/"):
                return None
            cl = r.headers.get("Content-Length")
            if cl and int(cl) > max_bytes:
                return None
            data = BytesIO()
            for chunk in r.iter_content(8192):
                if not chunk:
                    continue
                data.write(chunk)
                if data.tell() > max_bytes:
                    return None
            data.seek(0)
            return data, ctype
    except Exception:  # pragma: no cover
        return None


def publish_message(chat_id: str, title: str, body: str, url: str, image_url: Optional[str] = None, cfg=config) -> bool:
    if not chat_id:
        return False
    parse_mode = (cfg.TELEGRAM_PARSE_MODE or getattr(cfg, "PARSE_MODE", "HTML")).upper()
    limit = int(getattr(cfg, "TELEGRAM_MESSAGE_LIMIT", 4096))
    item = {"title": title, "content": body, "url": url}
    rewritten = rewrite.maybe_rewrite_item(item, cfg)
    body_current = rewritten.get("content", "") or ""
    message = _build_message(title or "", body_current, url or "", parse_mode)
    attempts = 0
    while len(message) > limit and attempts < 4:
        body_current = _smart_trim(body_current, max(0, len(body_current) - 100))
        message = _build_message(title or "", body_current, url or "", parse_mode)
        attempts += 1
    if len(message) > limit:
        body_current = _smart_trim(body_current, limit - len(message) + len(body_current) - 10)
        message = _build_message(title or "", body_current, url or "", parse_mode)

    mid: Optional[str] = None
    if image_url:
        img = _download_image(image_url, cfg)
        if img:
            data, mime = img
            res = _send_photo(chat_id, data, message, parse_mode, mime=mime)
            if res:
                mid = res[0]
    if mid is None:
        mid = _send_text(chat_id, message, parse_mode)
    if not mid:
        return False
    sleep = float(getattr(cfg, "PUBLISH_SLEEP_BETWEEN_SEC", 0))
    if sleep > 0:
        time.sleep(sleep)
    return True


# ---------------------------------------------------------------------------
# Moderation helpers
# ---------------------------------------------------------------------------

def send_moderation_preview(chat_id: str, item: Dict[str, Any], mod_id: int, cfg=config) -> Optional[str]:
    """Send preview message with inline buttons for moderation."""
    parse_mode = (cfg.TELEGRAM_PARSE_MODE or getattr(cfg, "PARSE_MODE", "HTML")).upper()
    caption, long_text = compose_preview(
        item.get("title", ""), item.get("content", ""), item.get("url", ""), parse_mode
    )
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅", "callback_data": f"mod:{mod_id}:approve"},
                {"text": "❌", "callback_data": f"mod:{mod_id}:reject"},
                {"text": "💤", "callback_data": f"mod:{mod_id}:snooze"},
                {"text": "✏️", "callback_data": f"mod:{mod_id}:edit"},
            ],
            [{"text": "🔗", "url": item.get("url", "") or ""}],
        ]
    }
    photo = item.get("tg_file_id") or item.get("image_url")
    mid = None
    if (
        cfg.PREVIEW_MODE != "text_only"
        and getattr(cfg, "ATTACH_IMAGES", True)
        and photo
    ):
        res = _send_photo(chat_id, photo, caption, parse_mode, reply_markup=keyboard)
        if res:
            mid = res[0]
            if long_text:
                _send_text(chat_id, long_text, parse_mode)
            return mid
        logger.warning("Failed to send photo preview for mod_id=%s; falling back to text", mod_id)
    return _send_text(chat_id, caption if not long_text else long_text, parse_mode, reply_markup=keyboard)


def publish_from_queue(conn: sqlite3.Connection, mod_id: int, text_override: Optional[str] = None, cfg=config) -> Optional[str]:
    cur = conn.execute("SELECT * FROM moderation_queue WHERE id = ?", (mod_id,))
    row = cur.fetchone()
    if not row:
        return None
    title = row["title"] or ""
    body = text_override or row["content"] or ""
    url = row["url"] or ""
    parse_mode = (cfg.TELEGRAM_PARSE_MODE or getattr(cfg, "PARSE_MODE", "HTML")).upper()
    caption, long_text = compose_preview(title, body, url, parse_mode)
    chat_id = getattr(cfg, "CHANNEL_CHAT_ID", "") or getattr(cfg, "CHANNEL_ID", "")
    mid: Optional[str] = None
    photo = row["tg_file_id"] or row["image_url"]
    if not row["tg_file_id"] and row["image_url"]:
        try:
            res = images.ensure_tg_file_id(row["image_url"], conn)
            if res:
                fid, ihash = res
                conn.execute(
                    "UPDATE moderation_queue SET tg_file_id = ?, image_hash = ? WHERE id = ?",
                    (fid, ihash, mod_id),
                )
                conn.commit()
                photo = fid
        except Exception:
            pass
    if (
        cfg.PREVIEW_MODE != "text_only"
        and getattr(cfg, "ATTACH_IMAGES", True)
        and photo
    ):
        res = _send_photo(chat_id, photo, caption, parse_mode)
        if res:
            mid = res[0]
            if long_text:
                _send_text(chat_id, long_text, parse_mode)
    if mid is None:
        mid = _send_text(chat_id, caption if not long_text else long_text, parse_mode)
    if mid:
        conn.execute(
            "UPDATE moderation_queue SET status = ?, channel_message_id = ?, published_at = strftime('%s','now') WHERE id = ?",
            ("PUBLISHED", mid, mod_id),
        )
        conn.commit()
    return mid

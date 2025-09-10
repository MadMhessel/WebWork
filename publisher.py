import json
import logging
import time
from io import BytesIO
from typing import Any, Dict, Optional, Tuple, Union
import sqlite3

import requests

from formatting import clean_html_tags, html_escape, truncate_by_chars

try:  # Pillow is optional
    from PIL import Image  # type: ignore
except Exception:  # pragma: no cover
    Image = None  # type: ignore

try:
    from . import config, db, rewrite, http_client
except ImportError:  # pragma: no cover
    import config  # type: ignore
    import db  # type: ignore
    import rewrite  # type: ignore
    import http_client  # type: ignore

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org"
_client_base_url: Optional[str] = None


# ---------------------------------------------------------------------------
# Client helpers
# ---------------------------------------------------------------------------


def init_telegram_client(token: Optional[str] = None) -> None:
    """Initialize base URL for Telegram Bot API."""
    global _client_base_url
    token = token or getattr(config, "BOT_TOKEN", "").strip()
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
    """Delegate HTML escaping to :mod:`formatting`."""

    return html_escape(text or "")


def _build_message(title: str, body: str, url: str, parse_mode: str) -> str:
    title = clean_html_tags(title)
    body = clean_html_tags(body)
    if parse_mode == "MarkdownV2":
        t = _escape_markdown_v2(title)
        b = _escape_markdown_v2(body)
        u = _escape_markdown_v2(url)
        return f"*{t}*\n\n{b}\n\n[Подробнее]({u})".strip()
    et = _escape_html(title)
    eb = _escape_html(body)
    eu = _escape_html(url)
    return f'<b>{et}</b>\n\n{eb}\n\nПодробнее: <a href="{eu}">{eu}</a>'.strip()


def _smart_trim(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    trimmed = truncate_by_chars(text, max_chars - 1)
    return trimmed + "…"


def _sanitize_md_tail(text: str) -> str:
    """Remove trailing characters that may break MarkdownV2."""
    if text is None:
        return text
    # drop dangling escape or formatting markers
    while text and text[-1] in _MD_V2_RESERVED:
        if len(text) >= 2 and text[-2] == "\\":
            break
        text = text[:-1]
    if text.endswith("\\"):
        text = text[:-1]
    return text


def compose_preview(
    title: str, body: str, url: str, parse_mode: str
) -> tuple[str, Optional[str]]:
    full = _build_message(title, body, url, parse_mode)
    caption_limit = int(getattr(config, "CAPTION_LIMIT", 1024))
    msg_limit = int(getattr(config, "TELEGRAM_MESSAGE_LIMIT", 4096))
    if len(full) <= caption_limit:
        if parse_mode == "MarkdownV2":
            full = _sanitize_md_tail(full)
        return full, None
    caption = _smart_trim(full, caption_limit)
    long_text = _smart_trim(full, msg_limit)
    if parse_mode == "MarkdownV2":
        caption = _sanitize_md_tail(caption)
        long_text = _sanitize_md_tail(long_text)
    return caption, long_text


def _normalize_parse_mode(mode: str) -> str:
    low = (mode or "HTML").strip().lower().replace(" ", "")
    if low == "markdownv2":
        return "MarkdownV2"
    if low == "html":
        return "HTML"
    return mode or "HTML"


def format_preview(post: Dict[str, Any], cfg=config) -> tuple[str, Optional[str]]:
    """Format a news post for Telegram preview with escaping and limits."""
    parse_mode = _normalize_parse_mode(
        getattr(cfg, "TELEGRAM_PARSE_MODE", getattr(cfg, "PARSE_MODE", "HTML"))
    )
    title = post.get("title", "")
    body = post.get("content", "") or post.get("text", "")
    url = post.get("url", "")
    return compose_preview(title, body, url, parse_mode)


# ---------------------------------------------------------------------------
# Telegram HTTP helpers
# ---------------------------------------------------------------------------


def _api_post(
    method: str, payload: Dict[str, Any], files: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
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


def _send_text(
    chat_id: str,
    text: str,
    parse_mode: str,
    reply_markup: Optional[dict] = None,
    reply_to_message_id: Optional[str] = None,
) -> Optional[str]:
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": (
            "true"
            if getattr(config, "TELEGRAM_DISABLE_WEB_PAGE_PREVIEW", False)
            else "false"
        ),
    }
    if reply_markup is not None:
        payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id
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

    photo_kind = "upload" if isinstance(photo, BytesIO) else "file_id"
    logger.info(
        "Sending photo: parse_mode=%s caption_len=%d type=%s",
        parse_mode,
        len(caption or ""),
        photo_kind,
    )

    if isinstance(photo, BytesIO):
        if not mime:
            raise ValueError("mime required when uploading BytesIO")
        files = {"photo": ("image", photo, mime)}
    else:
        if str(photo).startswith("http"):
            raise ValueError("photo URL not allowed; provide BytesIO or file_id")
        files = None
        payload["photo"] = photo

    if not _ensure_client():
        return None
    url = f"{_client_base_url}/sendPhoto"
    r = None
    try:
        r = requests.post(url, data=payload, files=files, timeout=30)
        if r.status_code != 200:
            logger.error("sendPhoto failed: HTTP %s", r.status_code)
            success = False
            j = None
        else:
            j = r.json()
            success = bool(j.get("ok"))
            if not success:
                logger.error("sendPhoto failed: %s", r.text[:200])
    except Exception as ex:  # pragma: no cover
        logger.exception("Exception during sendPhoto: %s", ex)
        success = False
        j = None
    if not success:
        return None

    res = j.get("result", {}) if j else {}
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
    parse_mode = _normalize_parse_mode(
        getattr(cfg, "TELEGRAM_PARSE_MODE", getattr(cfg, "PARSE_MODE", "HTML"))
    )
    return _send_text(chat_id, text, parse_mode)


def _download_image(url: str, cfg=config) -> Optional[Tuple[BytesIO, str]]:
    t = float(getattr(cfg, "IMAGE_TIMEOUT", 15))
    timeout = (t, t)
    max_bytes = int(getattr(cfg, "IMAGE_MAX_BYTES", 5 * 1024 * 1024))
    min_bytes = int(getattr(cfg, "MIN_IMAGE_BYTES", 4096))
    session = http_client.get_session()
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "ru,en;q=0.8",
        "Referer": url,
    }
    try:
        with session.get(
            url, timeout=timeout, stream=True, headers=headers, allow_redirects=True
        ) as r:
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
            if data.tell() < min_bytes:
                return None
            data.seek(0)
            if ctype in {"image/webp", "image/avif"} and Image is not None:
                try:
                    with Image.open(data) as im:
                        converted = BytesIO()
                        im.save(converted, format="JPEG", quality=85)
                        converted.seek(0)
                        return converted, "image/jpeg"
                except Exception:
                    return None
            return data, ctype
    except Exception:  # pragma: no cover
        return None


def publish_message(
    chat_id: str,
    title: str,
    body: str,
    url: str,
    image_url: Optional[str] = None,
    image_bytes: Optional[bytes] = None,
    image_mime: Optional[str] = None,
    credit: Optional[str] = None,
    cfg=config,
) -> bool:
    if not chat_id:
        return False
    parse_mode = _normalize_parse_mode(
        getattr(cfg, "TELEGRAM_PARSE_MODE", getattr(cfg, "PARSE_MODE", "HTML"))
    )
    limit = int(getattr(cfg, "TELEGRAM_MESSAGE_LIMIT", 4096))
    item = {"title": title, "content": body, "url": url}
    if image_url:
        item["image_url"] = image_url
    rewritten = rewrite.maybe_rewrite_item(item, cfg)
    body_current = rewritten.get("content", "") or ""
    caption, long_text = compose_preview(
        title or "", body_current, url or "", parse_mode
    )
    caption_limit = int(getattr(cfg, "CAPTION_LIMIT", 1024))
    extra_credit: Optional[str] = None
    if credit:
        if parse_mode == "MarkdownV2":
            credit_text = _escape_markdown_v2(credit)
            credit_tag = f"_Фото: {credit_text}_"
        else:
            credit_text = _escape_html(credit)
            credit_tag = f"<i>Фото: {credit_text}</i>"
        if len(caption) + 2 + len(credit_tag) <= caption_limit:
            caption = f"{caption}\n\n{credit_tag}"
        else:
            extra_credit = credit_tag
    limit = int(getattr(cfg, "TELEGRAM_MESSAGE_LIMIT", 4096))
    if long_text is None and len(caption) > limit:
        caption = _smart_trim(caption, limit)

    mid: Optional[str] = None
    photo: Optional[Union[BytesIO, str]] = None
    mime = None
    conn: Optional[sqlite3.Connection] = None
    if image_bytes:
        photo = BytesIO(image_bytes)
        mime = image_mime or "image/jpeg"
        if image_url:
            try:
                conn = db.connect()
            except Exception:  # pragma: no cover
                conn = None
    elif image_url:
        try:
            conn = db.connect()
        except Exception:  # pragma: no cover
            conn = None
        cached = db.get_cached_file_id(conn, image_url) if conn else None
        if cached:
            photo = cached
        else:
            dl = _download_image(image_url, cfg)
            if dl:
                photo, mime = dl
            else:
                photo = None
    if photo:
        res = _send_photo(chat_id, photo, caption, parse_mode, mime)
        if res:
            mid, fid = res
            if fid and image_url and conn:
                db.put_cached_file_id(conn, image_url, fid)
            if extra_credit:
                _send_text(chat_id, extra_credit, parse_mode, reply_to_message_id=mid)
            if long_text:
                _send_text(chat_id, long_text, parse_mode)
    if mid is None:
        mid = _send_text(chat_id, caption if not long_text else long_text, parse_mode)
        if extra_credit and mid:
            _send_text(chat_id, extra_credit, parse_mode, reply_to_message_id=mid)
    if not mid:
        return False
    sleep = float(getattr(cfg, "PUBLISH_SLEEP_BETWEEN_SEC", 0))
    if sleep > 0:
        time.sleep(sleep)
    return True


# ---------------------------------------------------------------------------
# Moderation helpers
# ---------------------------------------------------------------------------


def answer_callback_query(
    callback_query_id: str, text: Optional[str] = None, show_alert: bool = False
) -> None:
    """Acknowledge a button callback to stop the Telegram client's spinner."""
    payload: Dict[str, Any] = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    if show_alert:
        payload["show_alert"] = "true"
    _api_post("answerCallbackQuery", payload)


def remove_moderation_buttons(chat_id: str, message_id: Union[int, str]) -> None:
    """Remove inline keyboard from moderation preview message."""
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "reply_markup": json.dumps({"inline_keyboard": []}),
    }
    _api_post("editMessageReplyMarkup", payload)


def send_moderation_preview(
    chat_id: str, item: Dict[str, Any], mod_id: int, cfg=config
) -> Optional[str]:
    """Send preview message with inline buttons for moderation."""
    caption, long_text = format_preview(item, cfg)
    parse_mode = _normalize_parse_mode(
        getattr(cfg, "TELEGRAM_PARSE_MODE", getattr(cfg, "PARSE_MODE", "HTML"))
    )
    keyboard = {
        "inline_keyboard": [
            [{"text": "✅ Утвердить", "callback_data": f"mod:{mod_id}:approve"}],
            [
                {"text": "✏️ Заголовок", "callback_data": f"mod:{mod_id}:edit_title"},
                {"text": "📝 Текст", "callback_data": f"mod:{mod_id}:edit_text"},
            ],
            [{"text": "🏷️ Теги", "callback_data": f"mod:{mod_id}:edit_tags"}],
            [
                {"text": "💤 15м", "callback_data": f"mod:{mod_id}:snooze:15"},
                {"text": "1ч", "callback_data": f"mod:{mod_id}:snooze:60"},
                {"text": "3ч", "callback_data": f"mod:{mod_id}:snooze:180"},
            ],
            [{"text": "❌ Отклонить", "callback_data": f"mod:{mod_id}:reject"}],
            [{"text": "🔗", "url": item.get("url", "") or ""}],
        ]
    }
    photo: Optional[Union[BytesIO, str]] = None
    mime = None
    if cfg.PREVIEW_MODE != "text_only" and getattr(cfg, "ATTACH_IMAGES", True):
        photo = item.get("tg_file_id")
        if not photo and item.get("image_url"):
            src = item["image_url"]
            try:
                conn = db.connect()
            except Exception:  # pragma: no cover
                conn = None
            cached = db.get_cached_file_id(conn, src) if conn else None
            if cached:
                photo = cached
            else:
                dl = _download_image(src, cfg)
                if dl:
                    photo, mime = dl
    mid = None
    if photo:
        res = _send_photo(chat_id, photo, caption, parse_mode, mime, reply_markup=keyboard)
        if res:
            mid = res[0]
            if long_text:
                _send_text(chat_id, long_text, parse_mode)
            return mid
        logger.warning(
            "Failed to send photo preview for mod_id=%s; falling back to text", mod_id
        )
    return _send_text(
        chat_id,
        caption if not long_text else long_text,
        parse_mode,
        reply_markup=keyboard,
    )


def publish_from_queue(
    conn: sqlite3.Connection,
    mod_id: int,
    text_override: Optional[str] = None,
    cfg=config,
) -> Optional[str]:
    cur = conn.execute("SELECT * FROM moderation_queue WHERE id = ?", (mod_id,))
    row = cur.fetchone()
    if not row:
        return None
    title = row["title"] or ""
    body = text_override or row["content"] or ""
    url = row["url"] or ""
    parse_mode = _normalize_parse_mode(
        getattr(cfg, "TELEGRAM_PARSE_MODE", getattr(cfg, "PARSE_MODE", "HTML"))
    )
    caption, long_text = compose_preview(title, body, url, parse_mode)
    chat_id = getattr(cfg, "CHANNEL_CHAT_ID", "") or getattr(cfg, "CHANNEL_ID", "")
    mid: Optional[str] = None
    photo: Optional[Union[BytesIO, str]] = row["tg_file_id"]
    mime = None
    src_url = None
    if not photo and row["image_url"]:
        src_url = row["image_url"]
        cached = db.get_cached_file_id(conn, src_url)
        if cached:
            photo = cached
        else:
            dl = _download_image(src_url, cfg)
            if dl:
                photo, mime = dl
    if (
        cfg.PREVIEW_MODE != "text_only"
        and getattr(cfg, "ATTACH_IMAGES", True)
        and photo
    ):
        res = _send_photo(chat_id, photo, caption, parse_mode, mime)
        if res:
            mid, fid = res
            if fid and src_url:
                db.put_cached_file_id(conn, src_url, fid)
                conn.execute(
                    "UPDATE moderation_queue SET tg_file_id = ?, image_hash = ? WHERE id = ?",
                    (fid, None, mod_id),
                )
                conn.commit()
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

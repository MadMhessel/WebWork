import json
import logging
import time
from datetime import datetime
from typing import Any, Callable, Dict, Optional
import sqlite3

import requests

from formatting import clean_html_tags, html_escape, truncate_by_chars

try:  # pragma: no cover - package import in production
    from . import config, rewrite
except ImportError:  # pragma: no cover - direct script execution
    import config  # type: ignore
    import rewrite  # type: ignore

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
    if getattr(config, "DRY_RUN", False):
        logger.info("[DRY-RUN: READY] Telegram отправка отключена (DRY_RUN=1).")
    if not token:
        if not getattr(config, "DRY_RUN", False):
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
    if text is None:
        return text
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
    parse_mode = _normalize_parse_mode(
        getattr(cfg, "TELEGRAM_PARSE_MODE", getattr(cfg, "PARSE_MODE", "HTML"))
    )
    title = post.get("title", "")
    body = post.get("content", "") or post.get("text", "")
    url = post.get("url", "")
    return compose_preview(title, body, url, parse_mode)


def _parse_json_like(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return value


def _normalize_tags(value: Any) -> list[str]:
    raw = _parse_json_like(value)
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",")]
    elif isinstance(raw, (list, tuple, set)):
        parts = [str(p).strip() for p in raw]
    else:
        return []
    seen = []
    for part in parts:
        if part and part not in seen:
            seen.append(part)
    return seen


def _format_filter_flags(value: Any) -> str:
    raw = _parse_json_like(value)
    if not isinstance(raw, dict):
        return ""

    def _truthy(val: Any) -> Optional[bool]:
        if val is None:
            return None
        if isinstance(val, str):
            v = val.strip().lower()
            if v in {"", "null"}:
                return None
            if v in {"1", "true", "yes", "y", "да"}:
                return True
            if v in {"0", "false", "no", "n", "нет"}:
                return False
        try:
            return bool(int(val))
        except Exception:
            try:
                return bool(val)
            except Exception:
                return None

    region = _truthy(raw.get("region"))
    if region is None:
        region = _truthy(raw.get("region_ok"))
    topic = _truthy(raw.get("topic"))
    if topic is None:
        topic = _truthy(raw.get("topic_ok"))

    parts: list[str] = []
    if region is not None:
        parts.append(f"регион {'✅' if region else '✖️'}")
    if topic is not None:
        parts.append(f"тематика {'✅' if topic else '✖️'}")

    if not parts:
        return ""

    note = raw.get("note") or raw.get("reason")
    tail = f" ({note})" if note else ""
    return "⚙️ Фильтр: " + ", ".join(parts) + tail


def _format_relative_timestamp(ts_value: Any) -> Optional[str]:
    if ts_value is None:
        return None
    try:
        ts = int(float(ts_value))
    except Exception:
        return None
    if ts <= 0:
        return None
    dt = datetime.fromtimestamp(ts)
    now = datetime.now()
    delta = now - dt
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        total_seconds = 0

    if total_seconds < 60:
        rel = "менее минуты назад"
    elif total_seconds < 3600:
        minutes = max(1, total_seconds // 60)
        rel = f"{minutes} мин назад"
    elif total_seconds < 86400:
        hours = max(1, total_seconds // 3600)
        rel = f"{hours} ч назад"
    else:
        days = max(1, total_seconds // 86400)
        rel = f"{days} дн назад"
    stamp = dt.strftime("%d.%m %H:%M")
    return f"{stamp} ({rel})"


def _build_moderation_header(mod_id: int, item: Dict[str, Any]) -> str:
    pieces: list[str] = []

    source = (
        item.get("source_title")
        or item.get("source")
        or item.get("source_id")
        or ""
    )
    header = f"🗞 <b>#{mod_id}</b>"
    if source:
        header += f" • {_escape_html(str(source))}"

    fetched_line = _format_relative_timestamp(item.get("fetched_at"))
    if fetched_line:
        header += f" • {fetched_line}"

    pieces.append(header)

    tags = _normalize_tags(item.get("tags"))
    if tags:
        pieces.append("🏷️ " + _escape_html(", ".join(tags)))

    filter_line = _format_filter_flags(item.get("reasons"))
    if filter_line:
        pieces.append(filter_line)

    credit = item.get("credit")
    if credit:
        pieces.append("👤 " + _escape_html(str(credit)))

    pieces.append(
        "ℹ️ Используйте кнопки ниже, чтобы утвердить, отредактировать или отложить запись."
    )

    return "\n".join(piece for piece in pieces if piece).strip()


# ---------------------------------------------------------------------------
# Telegram HTTP helpers
# ---------------------------------------------------------------------------


def _api_post(
    method: str, payload: Dict[str, Any], files: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    if getattr(config, "DRY_RUN", False):
        safe_payload = {k: v for k, v in payload.items() if k != "reply_markup"}
        logger.info(
            "[DRY-RUN: READY] %s -> %s", method, json.dumps(safe_payload, ensure_ascii=False)
        )
        # emulate Telegram response structure so остальной код не падал
        return {"ok": True, "result": {"message_id": "dry-run"}}
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
    except Exception as ex:  # pragma: no cover - network failure guard
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


def _send_with_retry(action: Callable[[], Optional[str]], cfg=config) -> Optional[str]:
    mode = getattr(cfg, "ON_SEND_ERROR", "retry").lower()
    retries = max(0, int(getattr(cfg, "PUBLISH_MAX_RETRIES", 0)))
    backoff = max(0.0, float(getattr(cfg, "RETRY_BACKOFF_SECONDS", 0.0)))

    for attempt in range(retries + 1):
        mid = action()
        if mid:
            return mid
        if mode == "ignore":
            return None
        if mode == "raise":
            raise RuntimeError("Не удалось отправить сообщение в Telegram")
        if mode != "retry" or attempt == retries:
            break
        sleep_for = backoff * (attempt + 1)
        if sleep_for > 0:
            time.sleep(sleep_for)
    return None


# ---------------------------------------------------------------------------
# Public helpers used in tests and pipeline
# ---------------------------------------------------------------------------


def send_message(chat_id: str, text: str, cfg=config) -> Optional[str]:
    parse_mode = _normalize_parse_mode(
        getattr(cfg, "TELEGRAM_PARSE_MODE", getattr(cfg, "PARSE_MODE", "HTML"))
    )
    return _send_text(chat_id, text, parse_mode)


def publish_message(
    chat_id: str,
    title: str,
    body: str,
    url: str,
    *,
    cfg=config,
) -> bool:
    if not chat_id:
        return False
    parse_mode = _normalize_parse_mode(
        getattr(cfg, "TELEGRAM_PARSE_MODE", getattr(cfg, "PARSE_MODE", "HTML"))
    )
    item = {"title": title, "content": body, "url": url}
    rewritten = rewrite.maybe_rewrite_item(item, cfg)
    body_current = rewritten.get("content", "") or ""
    caption, long_text = compose_preview(title or "", body_current, url or "", parse_mode)

    messages: list[str] = []
    if caption:
        messages.append(caption)
    if long_text and long_text != caption:
        messages.append(long_text)

    msg_limit = int(getattr(cfg, "TELEGRAM_MESSAGE_LIMIT", 4096))
    last_mid: Optional[str] = None
    for idx, text in enumerate(messages):
        trimmed = text if len(text) <= msg_limit else _smart_trim(text, msg_limit)

        def _send() -> Optional[str]:
            return _send_text(
                chat_id,
                trimmed,
                parse_mode,
                reply_to_message_id=last_mid if idx > 0 else None,
            )

        mid = _send_with_retry(_send, cfg)
        if not mid:
            return False
        last_mid = mid

    sleep = float(getattr(cfg, "PUBLISH_SLEEP_BETWEEN_SEC", 0))
    if sleep > 0:
        time.sleep(sleep)
    return bool(messages)


# ---------------------------------------------------------------------------
# Moderation helpers
# ---------------------------------------------------------------------------


def answer_callback_query(
    callback_query_id: str, text: Optional[str] = None, show_alert: bool = False
) -> None:
    payload: Dict[str, Any] = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    if show_alert:
        payload["show_alert"] = "true"
    _api_post("answerCallbackQuery", payload)


def remove_moderation_buttons(chat_id: str, message_id: int | str) -> None:
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "reply_markup": json.dumps({"inline_keyboard": []}),
    }
    _api_post("editMessageReplyMarkup", payload)


def send_moderation_preview(
    chat_id: str, item: Dict[str, Any], mod_id: int, cfg=config
) -> Optional[str]:
    caption, long_text = format_preview(item, cfg)
    parse_mode = _normalize_parse_mode(
        getattr(cfg, "TELEGRAM_PARSE_MODE", getattr(cfg, "PARSE_MODE", "HTML"))
    )
    header = _build_moderation_header(mod_id, item)
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

    messages: list[str] = []
    if caption:
        first = f"{header}\n\n{caption}" if header else caption
        messages.append(first.strip())
    elif header:
        messages.append(header)
    if long_text and long_text != caption:
        messages.append(long_text)

    msg_limit = int(getattr(cfg, "TELEGRAM_MESSAGE_LIMIT", 4096))
    mid: Optional[str] = None
    for idx, text in enumerate(messages):
        trimmed = text if len(text) <= msg_limit else _smart_trim(text, msg_limit)

        def _send() -> Optional[str]:
            return _send_text(
                chat_id,
                trimmed,
                parse_mode,
                reply_markup=keyboard if idx == 0 else None,
                reply_to_message_id=mid if idx > 0 else None,
            )

        new_mid = _send_with_retry(_send, cfg)
        if not new_mid:
            return mid if mid else None
        if idx == 0:
            mid = new_mid
    return mid


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

    messages: list[str] = []
    if caption:
        messages.append(caption)
    if long_text and long_text != caption:
        messages.append(long_text)

    msg_limit = int(getattr(cfg, "TELEGRAM_MESSAGE_LIMIT", 4096))
    mid: Optional[str] = None
    for idx, text in enumerate(messages):
        trimmed = text if len(text) <= msg_limit else _smart_trim(text, msg_limit)

        def _send() -> Optional[str]:
            return _send_text(
                chat_id,
                trimmed,
                parse_mode,
                reply_to_message_id=mid if idx > 0 else None,
            )

        new_mid = _send_with_retry(_send, cfg)
        if not new_mid:
            return mid if mid else None
        if idx == 0:
            mid = new_mid
    if not mid:
        return None

    conn.execute(
        "UPDATE moderation_queue SET status = ?, channel_message_id = ?, published_at = strftime('%s','now') WHERE id = ?",
        ("PUBLISHED", mid, mod_id),
    )
    conn.commit()
    return mid


__all__ = [
    "init_telegram_client",
    "send_message",
    "publish_message",
    "compose_preview",
    "format_preview",
    "answer_callback_query",
    "remove_moderation_buttons",
    "send_moderation_preview",
    "publish_from_queue",
]

import json
import time
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Callable, Dict, Optional, Sequence
import re
import sqlite3
from urllib.parse import urlparse

import requests

from formatting import clean_html_tags, html_escape, truncate_by_chars

import moderation
from logging_setup import audit, get_logger, mask_secrets

try:  # pragma: no cover - package import in production
    from . import config, rewrite
except ImportError:  # pragma: no cover - direct script execution
    import config  # type: ignore
    import rewrite  # type: ignore
from webwork.utils.formatting import chunk_text, safe_format, TG_TEXT_LIMIT
from webwork.router import route_and_publish

log = get_logger("webwork.bot")

_API_BASE = "https://api.telegram.org"
_client_base_url: Optional[str] = None

_RAW_ALIAS_CACHE: dict[str, int] = {}



# ---------------------------------------------------------------------------
# Client helpers
# ---------------------------------------------------------------------------


def init_telegram_client(token: Optional[str] = None) -> None:
    """Initialize base URL for Telegram Bot API."""
    global _client_base_url
    token = token or getattr(config, "BOT_TOKEN", "").strip()
    if getattr(config, "DRY_RUN", False):
        log.info("[DRY-RUN: READY] Telegram отправка отключена (DRY_RUN=1).")
    if not token:
        if not getattr(config, "DRY_RUN", False):
            log.warning("BOT_TOKEN пуст — отправка в Telegram отключена.")
        _client_base_url = None
        return
    _client_base_url = f"{_API_BASE}/bot{token}"


def _ensure_client() -> bool:
    if _client_base_url is None:
        init_telegram_client()
    return _client_base_url is not None


def _log_api_error(response: requests.Response, method: str, params: Dict[str, Any]) -> None:
    try:
        err = response.json()
    except ValueError:
        err = {"raw_text": response.text}
    try:
        payload_dump = json.dumps(params, ensure_ascii=False)[:800]
    except (TypeError, ValueError):
        payload_dump = str(params)
    log.warning(
        "[RAW] publish FAIL %s %s | method=%s payload=%s",
        response.status_code,
        err,
        method,
        payload_dump,
    )


def tg_api(method: str, **params):
    token = getattr(config, "TELEGRAM_BOT_TOKEN", getattr(config, "BOT_TOKEN", ""))
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")
    url = f"{_API_BASE}/bot{token}/{method}"
    max_attempts = 5
    base_sleep = 1.5
    attempt = 0
    while True:
        attempt += 1
        try:
            response = requests.post(url, json=params, timeout=(5, 30))
        except requests.RequestException as exc:
            if attempt >= max_attempts:
                log.warning("RAW: метод %s — ошибка сети: %s", method, exc)
                raise
            wait = base_sleep * (2 ** (attempt - 1))
            log.warning(
                "RAW: метод %s — сеть не ответила, повтор через %.1f с (%s)",
                method,
                wait,
                exc,
            )
            time.sleep(wait)
            continue

        if response.status_code in {429} or response.status_code >= 500:
            if attempt >= max_attempts:
                _log_api_error(response, method, params)
                log.warning(
                    "RAW: метод %s — код %s после %s попыток", method, response.status_code, attempt
                )
                response.raise_for_status()
            wait = base_sleep * (2 ** (attempt - 1))
            log.warning(
                "RAW: метод %s — код %s, повтор через %.1f с",
                method,
                response.status_code,
                wait,
            )
            time.sleep(wait)
            continue

        if response.status_code >= 400:
            _log_api_error(response, method, params)
            response.raise_for_status()

        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            log.warning("RAW: метод %s — не удалось распарсить ответ: %s", method, exc)
            raise
        if not payload.get("ok"):
            raise RuntimeError(payload)
        return payload.get("result")


def get_from_chat_id(alias: str) -> int:
    normalized = alias.strip().lstrip("@")
    if not normalized:
        raise ValueError("Пустой alias")
    if normalized in _RAW_ALIAS_CACHE:
        return _RAW_ALIAS_CACHE[normalized]
    result = tg_api("getChat", chat_id=f"@{normalized}")
    chat_id = int(result["id"])
    _RAW_ALIAS_CACHE[normalized] = chat_id
    return chat_id


def try_copy_or_forward(item: Dict[str, Any]) -> bool:
    alias = (item.get("tg_alias") or "").strip()
    mid = item.get("tg_msg_id")
    if not alias or mid in {None, ""}:
        return False
    strategy = getattr(config, "RAW_FORWARD_STRATEGY", "copy")
    method = "copyMessage" if strategy == "copy" else "forwardMessage"
    try:
        from_chat_id = get_from_chat_id(alias)
        tg_api(
            method,
            chat_id=getattr(config, "RAW_REVIEW_CHAT_ID", ""),
            from_chat_id=from_chat_id,
            message_id=int(mid),
        )
        log.info("RAW: %s %s/%s успешно", method, alias, mid)
        return True
    except Exception as exc:  # pragma: no cover - сетевые ошибки зависят от среды
        log.warning("RAW %s failed for %s/%s: %s", method, alias, mid, exc)
        return False


def publish_raw(items: Sequence[Dict[str, Any]]) -> None:
    if not items:
        log.info("RAW: элементов нет, отправка пропущена")
        return
    chat_id = getattr(config, "RAW_REVIEW_CHAT_ID", "")
    if not chat_id:
        log.warning("RAW: RAW_REVIEW_CHAT_ID не задан, публикация невозможна")
        return
    strategy = getattr(config, "RAW_FORWARD_STRATEGY", "copy")
    log.info("RAW: отправка %d элементов (стратегия=%s)", len(items), strategy)
    for item in items:
        sent = False
        if strategy in {"copy", "forward"}:
            sent = try_copy_or_forward(item)
        if sent:
            continue
        title = (item.get("title") or "").strip()
        body = (item.get("content") or "").strip()
        url = (item.get("url") or "").strip()
        parts = []
        if title:
            parts.append(title)
        if url:
            parts.append(url)
        elif body:
            parts.append(body)
        text = "\n".join(parts).strip()
        if not text:
            log.warning("RAW: пропуск пустого элемента %s", item)
            continue
        try:
            parse_mode = _normalize_parse_mode(
                getattr(config, "TELEGRAM_PARSE_MODE", getattr(config, "PARSE_MODE", "HTML"))
            )
            mid = _send_text_chunks(chat_id, text, parse_mode, cfg=config)
            if mid:
                log.info("RAW: fallback sendMessage успешно (%s)", url or item.get("guid"))
            else:
                log.warning("RAW: fallback sendMessage не вернул message_id (%s)", url)
        except Exception as exc:  # pragma: no cover - сетевые ошибки
            log.warning("RAW sendMessage failed: %s", exc)
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

    rubric = item.get("rubric")
    domain = item.get("source_domain") or item.get("source_domain_hint")
    rubric_parts: list[str] = []
    if rubric:
        rubric_parts.append(f"Рубрика: <b>{_escape_html(str(rubric))}</b>")
    if domain:
        rubric_parts.append(f"Источник: <i>{_escape_html(str(domain))}</i>")
    if rubric_parts:
        pieces.append(" · ".join(rubric_parts))

    triggers = _parse_json_like(item.get("triggers"))
    if triggers:
        if isinstance(triggers, (list, tuple, set)):
            trig_text = ", ".join(str(t) for t in triggers if t)
        else:
            trig_text = str(triggers)
        if trig_text:
            pieces.append("⚙️ Триггеры: " + _escape_html(trig_text))

    flags = moderation.parse_flags(item.get("moderation_flags"))
    if flags:
        flag_names = ", ".join(flag.label or flag.key for flag in flags)
        pieces.append("🚩 Флаги: " + _escape_html(flag_names))

    trust_summary = _parse_json_like(item.get("trust_summary"))
    if isinstance(trust_summary, dict) and trust_summary:
        parts = []
        if trust_summary.get("min") is not None:
            parts.append(f"min={float(trust_summary['min']):.1f}")
        if trust_summary.get("avg") is not None:
            parts.append(f"avg={float(trust_summary['avg']):.1f}")
        if trust_summary.get("max") is not None:
            parts.append(f"max={float(trust_summary['max']):.1f}")
        if parts:
            pieces.append("🤝 Trust: " + _escape_html(", ".join(parts)))

    if bool(item.get("needs_confirmation")):
        reasons = _parse_json_like(item.get("confirmation_reasons"))
        if isinstance(reasons, (list, tuple)):
            reason_text = "; ".join(str(r) for r in reasons if r)
        else:
            reason_text = str(reasons or "")
        msg = "☑️ Требуются подтверждения"
        if reason_text:
            msg += f": {_escape_html(reason_text)}"
        pieces.append(msg)

    if bool(item.get("quality_note_required")):
        pieces.append("ℹ️ Добавьте ремарку о качестве/подтверждении при публикации.")

    credit = item.get("credit")
    if credit:
        pieces.append("👤 " + _escape_html(str(credit)))

    pieces.append("ℹ️ Отредактируйте текст вручную и при необходимости опубликуйте в канал.")

    return "\n".join(piece for piece in pieces if piece).strip()


# ---------------------------------------------------------------------------
# Publication formatting helpers
# ---------------------------------------------------------------------------


_TOKEN_RE = re.compile(r"<[^>]+>|[^<]+")
_SELF_CLOSING_TAGS = {"br", "br/", "hr", "img", "input", "meta", "link"}
_ALLOWED_TAGS = {"b", "i", "u", "s", "a", "code", "pre", "blockquote", "br"}
_BLOCKING_TAGS = {"a", "code", "pre", "blockquote"}
_MIN_CHUNK_LENGTH = 160
_BR_RE = re.compile(r"<br\s*/?>", re.I)


def _sanitize_for_telegram_html(text: str) -> str:
    if not text:
        return ""

    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = cleaned.replace("&nbsp;", " ")
    cleaned = re.sub(r"<\s*strong[^>]*>", "<b>", cleaned, flags=re.I)
    cleaned = re.sub(r"<\s*/\s*strong\s*>", "</b>", cleaned, flags=re.I)
    cleaned = re.sub(r"<\s*em[^>]*>", "<i>", cleaned, flags=re.I)
    cleaned = re.sub(r"<\s*/\s*em\s*>", "</i>", cleaned, flags=re.I)
    cleaned = re.sub(r"<\s*p(?!re)[^>]*>", "", cleaned, flags=re.I)
    cleaned = re.sub(r"<\s*/\s*p(?!re)\s*>", "<br><br>", cleaned, flags=re.I)
    cleaned = re.sub(r"<\s*hr[^>]*>", "<br><br>", cleaned, flags=re.I)
    cleaned = re.sub(r"<\s*/?\s*(?:div|section)[^>]*>", "<br>", cleaned, flags=re.I)
    cleaned = re.sub(r"<\s*li[^>]*>", "<br>• ", cleaned, flags=re.I)
    cleaned = re.sub(r"<\s*/\s*li\s*>", "", cleaned, flags=re.I)
    cleaned = re.sub(r"<\s*/?\s*(?:ul|ol)[^>]*>", "<br>", cleaned, flags=re.I)
    cleaned = re.sub(r"<\s*span[^>]*>", "", cleaned, flags=re.I)
    cleaned = re.sub(r"<\s*/\s*span\s*>", "", cleaned, flags=re.I)
    cleaned = _BR_RE.sub("<br>", cleaned)
    cleaned = re.sub(r"(?:<br>\s*){3,}", "<br><br>", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip()
    return cleaned


def _parse_tag(token: str) -> tuple[str, str] | None:
    token = token.strip()
    if not (token.startswith("<") and token.endswith(">")):
        return None
    inner = token[1:-1].strip()
    if not inner:
        return None
    if inner.startswith("!") or inner.startswith("?"):
        return None
    if inner.startswith("/"):
        name = inner[1:].strip().split(None, 1)[0].lower()
        return "end", name
    name = inner.split(None, 1)[0].lower()
    if name.endswith("/"):
        name = name[:-1]
    if name in _SELF_CLOSING_TAGS or inner.endswith("/"):
        return "self", name
    return "start", name


def _closing_suffix(stack_state: list[tuple[str, str]]) -> str:
    return "".join(f"</{name}>" for name, _ in reversed(stack_state))


def _extend_entity_piece(
    piece: str, remainder: str, *, current_len: int, closing_len: int, limit: int
) -> str:
    if "&" not in piece:
        return piece
    last_amp = piece.rfind("&")
    if last_amp == -1 or ";" in piece[last_amp:]:
        return piece
    extra_end = remainder.find(";")
    if extra_end == -1:
        return piece
    candidate = piece + remainder[: extra_end + 1]
    if current_len + len(candidate) + closing_len <= limit:
        return candidate
    return piece


def split_html_message(text: str, limit: int = 4000) -> list[str]:
    """Split ``text`` into HTML-safe chunks respecting ``limit`` characters."""

    sanitized = _sanitize_for_telegram_html(text)
    if not sanitized:
        return []

    limit = max(1, int(limit))
    tokens = list(_TOKEN_RE.findall(sanitized))
    parts: list[str] = []
    stack: list[tuple[str, str]] = []
    current: list[str] = []
    current_len = 0
    snapshot: dict[str, Any] | None = None

    def closing_length() -> int:
        return len(_closing_suffix(stack))

    def reset_state(state: list[tuple[str, str]]) -> None:
        nonlocal stack, current, current_len
        stack = list(state)
        current = [token for _, token in stack]
        current_len = sum(len(token) for _, token in stack)

    def emit_chunk(tokens_subset: list[str], stack_state: list[tuple[str, str]]) -> None:
        chunk = "".join(tokens_subset) + _closing_suffix(stack_state)
        plain = re.sub(r"<[^>]+>", "", chunk)
        if chunk.strip() and plain.strip():
            parts.append(chunk)

    def flush_current() -> None:
        nonlocal snapshot
        if not current:
            return
        emit_chunk(current, stack)
        snapshot = None
        reset_state(stack)

    def flush_snapshot() -> None:
        nonlocal snapshot, idx
        if not snapshot:
            flush_current()
            return
        emit_chunk(snapshot["tokens"], snapshot["stack"])
        reset_state(snapshot["stack"])
        idx = snapshot["index"]
        snapshot = None

    def record_safe(index: int) -> None:
        return

    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        tag = _parse_tag(token)
        if tag is None:
            remaining = token
            while remaining:
                avail = limit - (current_len + closing_length())
                if avail <= 0:
                    if snapshot:
                        flush_snapshot()
                        continue
                    if current:
                        flush_current()
                        continue
                    avail = limit - closing_length()
                    if avail <= 0:
                        avail = limit
                if current and (len(remaining) + current_len + closing_length() > limit):
                    flush_current()
                    continue
                piece = remaining[:avail]
                piece = _extend_entity_piece(
                    piece,
                    remaining[avail:],
                    current_len=current_len,
                    closing_len=closing_length(),
                    limit=limit,
                )
                if not piece:
                    piece = remaining[:avail]
                current.append(piece)
                current_len += len(piece)
                remaining = remaining[len(piece) :]
                if current_len + closing_length() >= limit:
                    if snapshot:
                        remaining = piece + remaining
                        flush_snapshot()
                        continue
                    else:
                        flush_current()
                        continue
            idx += 1
            continue

        kind, name = tag
        if name not in _ALLOWED_TAGS:
            idx += 1
            continue

        token_len = len(token)
        if kind == "start" and name != "br":
            while current_len + token_len + closing_length() > limit and current:
                if snapshot:
                    flush_snapshot()
                else:
                    flush_current()
            current.append(token)
            current_len += token_len
            stack.append((name, token))
            if name in _BLOCKING_TAGS:
                snapshot = None
            idx += 1
            continue

        if kind == "self" or (kind == "start" and name == "br"):
            token_text = "<br>" if name == "br" else token
            token_len = len(token_text)
            while current_len + token_len + closing_length() > limit and current:
                if snapshot:
                    flush_snapshot()
                else:
                    flush_current()
            current.append(token_text)
            current_len += token_len
            if name == "br":
                record_safe(idx + 1)
            idx += 1
            continue

        # closing tag
        if stack and stack[-1][0] == name:
            while current_len + token_len + closing_length() - len(f"</{name}>") > limit and current:
                if snapshot:
                    flush_snapshot()
                else:
                    flush_current()
            current.append(token)
            current_len += token_len
            stack.pop()
            if not stack:
                record_safe(idx + 1)
        else:
            # mismatched closing treated as text
            remaining = token
            while remaining:
                avail = limit - (current_len + closing_length())
                if avail <= 0:
                    if snapshot:
                        flush_snapshot()
                        continue
                    if current:
                        flush_current()
                        continue
                    avail = limit
                piece = remaining[:avail]
                current.append(piece)
                current_len += len(piece)
                remaining = remaining[len(piece) :]
        idx += 1

    if current:
        emit_chunk(current, stack)

    if not parts:
        return []

    merged: list[str] = []
    i = 0
    while i < len(parts):
        chunk = parts[i]
        if i < len(parts) - 1 and len(chunk) < _MIN_CHUNK_LENGTH:
            nxt = parts[i + 1]
            if len(chunk) + len(nxt) <= limit:
                chunk = chunk + "\n\n" + nxt
                i += 1
        merged.append(chunk)
        i += 1

    return merged


def _build_publication_header(item: Dict[str, Any]) -> str:
    rubric = item.get("rubric") or "objects"
    domain = item.get("source_domain")
    if not domain:
        url = item.get("url", "")
        parsed = urlparse(url)
        domain = (parsed.hostname or "").lower()
        if domain.startswith("www."):
            domain = domain[4:]
    header = f"Рубрика: <b>{_escape_html(str(rubric))}</b>"
    if domain:
        header += f" · Источник: <i>{_escape_html(domain)}</i>"
    flags = moderation.parse_flags(item.get("moderation_flags"))
    if flags:
        header += " (после ревью)"
    return header


def _prepare_publication_chunks(
    item: Dict[str, Any], max_chars: int
) -> list[str]:
    parse_mode = "HTML"
    title = item.get("title", "")
    body = item.get("content", "") or item.get("text", "")
    url = item.get("url", "")
    body_block = _build_message(title, body, url, parse_mode)
    header = _build_publication_header(item)
    combined = f"{header}\n\n{body_block}".strip()
    chunks = split_html_message(combined, max_chars)
    if len(chunks) > 1:
        total = len(chunks)
        chunks = [f"({idx}/{total}) {chunk}" for idx, chunk in enumerate(chunks, 1)]
    return chunks


def _send_chunks(
    chat_id: str,
    chunks: list[str],
    cfg,
) -> Optional[str]:
    if not chunks:
        return None
    parse_mode = "HTML"
    msg_limit = int(getattr(cfg, "TELEGRAM_MESSAGE_LIMIT", 4096))
    first_mid: Optional[str] = None
    last_mid: Optional[str] = None
    for idx, chunk in enumerate(chunks):
        trimmed = chunk if len(chunk) <= msg_limit else _smart_trim(chunk, msg_limit)

        def _send() -> Optional[str]:
            return _send_text(
                chat_id,
                trimmed,
                parse_mode,
                reply_to_message_id=last_mid if idx > 0 else None,
            )

        mid = _send_with_retry(_send, cfg)
        if not mid:
            return None
        if first_mid is None:
            first_mid = mid
        last_mid = mid
    sleep = float(getattr(cfg, "PUBLISH_SLEEP_BETWEEN_SEC", 0))
    if sleep > 0:
        time.sleep(sleep)
    return first_mid

# ---------------------------------------------------------------------------
# Telegram HTTP helpers
# ---------------------------------------------------------------------------


def _api_post(
    method: str, payload: Dict[str, Any], files: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    if getattr(config, "DRY_RUN", False):
        safe_payload = {k: v for k, v in payload.items() if k != "reply_markup"}
        log.info(
            "[DRY-RUN: READY] %s -> %s",
            method,
            mask_secrets(json.dumps(safe_payload, ensure_ascii=False)),
        )
        # emulate Telegram response structure so остальной код не падал
        return {"ok": True, "result": {"message_id": "dry-run"}}
    if not _ensure_client():
        return None
    url = f"{_client_base_url}/{method}"
    safe_url = mask_secrets(url)
    max_attempts = 2
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(url, data=payload, files=files, timeout=30)
        except Exception:  # pragma: no cover - network failure guard
            log.exception("Исключение при вызове Telegram %s (%s)", method, safe_url)
            return None
        status = response.status_code
        text = response.text
        try:
            data = response.json()
        except ValueError:
            log.error(
                "Некорректный ответ Telegram %s (%s): %s",
                method,
                safe_url,
                mask_secrets(text),
            )
            return None

        ok = bool(data.get("ok"))
        description = mask_secrets(data.get("description") or text)
        retry_after = None
        if status == 429:
            params = data.get("parameters") or {}
            try:
                retry_after = float(params.get("retry_after", 0) or 0)
            except (TypeError, ValueError):
                retry_after = 0
            if retry_after and attempt < max_attempts:
                log.warning(
                    "Telegram %s (%s) статус=%s ok=%s retry_after=%s",
                    method,
                    safe_url,
                    status,
                    ok,
                    retry_after,
                )
                time.sleep(retry_after)
                continue
            if retry_after:
                log.error(
                    "Telegram %s (%s) статус=%s ok=%s retry_after=%s — попытки исчерпаны",
                    method,
                    safe_url,
                    status,
                    ok,
                    retry_after,
                )

        if not ok:
            level = log.warning if status < 500 else log.error
            level(
                "Telegram %s (%s) статус=%s ok=%s ошибка=%s",
                method,
                safe_url,
                status,
                ok,
                description,
            )
            return None

        if status != 200:
            log.error(
                "Ошибка HTTP %s (%s): статус=%s тело=%s",
                method,
                safe_url,
                status,
                description,
            )
            return None

        result = data.get("result") or {}
        message_id = result.get("message_id")
        log.info(
            "Telegram %s (%s) статус=%s ok=%s%s",
            method,
            safe_url,
            status,
            ok,
            f" message_id={message_id}" if message_id else "",
        )
        return data
    return None


def _send_text(
    chat_id: str,
    text: str,
    parse_mode: str,
    reply_to_message_id: Optional[str] = None,
) -> Optional[str]:
    log.info(
        "Отправка sendMessage: chat_id=%s reply_to=%s длина=%s",
        chat_id,
        reply_to_message_id,
        len(text or ""),
    )
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
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id
    j = _api_post("sendMessage", payload)
    if not j:
        log.warning("sendMessage не вернул ответ: chat_id=%s", chat_id)
        return None
    result = j.get("result", {}) or {}
    message_id = result.get("message_id")
    if message_id is None:
        log.warning("sendMessage не вернул message_id: chat_id=%s", chat_id)
        return None
    log.info("Отправлено сообщение: chat_id=%s message_id=%s", chat_id, message_id)
    return str(message_id)


def _send_text_chunks(
    chat_id: str,
    text: str,
    parse_mode: str,
    *,
    reply_to_message_id: Optional[str] = None,
    cfg=config,
) -> Optional[str]:
    limit = min(int(getattr(cfg, "TELEGRAM_MESSAGE_LIMIT", TG_TEXT_LIMIT)), TG_TEXT_LIMIT)
    formatted = safe_format(text or "", parse_mode)
    chunks = chunk_text(formatted, limit)
    if not chunks:
        chunks = [""]
    last_mid = reply_to_message_id
    first_mid: Optional[str] = None

    for idx, chunk in enumerate(chunks):
        def _send() -> Optional[str]:
            return _send_text(
                chat_id,
                chunk,
                parse_mode,
                reply_to_message_id=last_mid,
            )

        mid = _send_with_retry(_send, cfg)
        if not mid:
            return first_mid
        if first_mid is None:
            first_mid = mid
        last_mid = mid
    return first_mid


def _send_with_retry(action: Callable[[], Optional[str]], cfg=config) -> Optional[str]:
    mode = getattr(cfg, "ON_SEND_ERROR", "retry").lower()
    retries = max(0, int(getattr(cfg, "PUBLISH_MAX_RETRIES", 0)))
    backoff = max(0.0, float(getattr(cfg, "RETRY_BACKOFF_SECONDS", 0.0)))

    for attempt in range(retries + 1):
        try:
            mid = action()
        except Exception as exc:
            log.warning(
                "Ошибка отправки (попытка %s): %s",
                attempt + 1,
                exc,
                exc_info=True,
            )
            mid = None
        if mid:
            if attempt:
                log.info("Успех после %s попытки: message_id=%s", attempt + 1, mid)
            return mid
        if mode == "ignore":
            return None
        if mode == "raise":
            raise RuntimeError("Не удалось отправить сообщение в Telegram")
        if mode != "retry" or attempt == retries:
            break
        log.warning(
            "Неудачная попытка отправки %s/%s — ожидание %.2f с",
            attempt + 1,
            retries + 1,
            backoff * (attempt + 1),
        )
        sleep_for = backoff * (attempt + 1)
        if sleep_for > 0:
            time.sleep(sleep_for)
    log.error("Отправка не удалась после %s попыток", retries + 1)
    return None


# ---------------------------------------------------------------------------
# Public helpers used in tests and pipeline
# ---------------------------------------------------------------------------


def send_message(chat_id: str, text: str, cfg=config) -> Optional[str]:
    parse_mode = _normalize_parse_mode(
        getattr(cfg, "TELEGRAM_PARSE_MODE", getattr(cfg, "PARSE_MODE", "HTML"))
    )
    log.info("Запрос на отправку простого сообщения: chat_id=%s", chat_id)
    mid = _send_text_chunks(chat_id, text, parse_mode, cfg=cfg)
    if mid:
        log.info("Простое сообщение отправлено: chat_id=%s message_id=%s", chat_id, mid)
    else:
        log.warning("Не удалось отправить простое сообщение: chat_id=%s", chat_id)
    return mid


def publish_structured_item(
    chat_id: str,
    item: Dict[str, Any],
    *,
    cfg=config,
    rewrite_item: bool = True,
) -> Optional[str]:
    if not chat_id:
        return None
    data = dict(item)
    if rewrite_item:
        data = rewrite.maybe_rewrite_item(data, cfg)
    msg_limit = int(getattr(cfg, "TELEGRAM_MESSAGE_LIMIT", 4096))
    chunk_limit = min(4000, msg_limit)
    chunks = _prepare_publication_chunks(data, chunk_limit)
    log.info(
        "Публикация карточки: chat_id=%s source=%s title=%s",
        chat_id,
        data.get("source"),
        data.get("title"),
    )
    mid = _send_chunks(chat_id, chunks, cfg)
    if mid:
        log.info(
            "Публикация успешна: chat_id=%s message_id=%s url=%s",
            chat_id,
            mid,
            data.get("url"),
        )
        audit(
            "publish.success",
            chat_id=chat_id,
            message_id=mid,
            source=data.get("source"),
            url=data.get("url"),
            title=data.get("title"),
        )
    else:
        log.error(
            "Публикация не удалась: chat_id=%s url=%s title=%s",
            chat_id,
            data.get("url"),
            data.get("title"),
        )
        audit(
            "publish.failure",
            chat_id=chat_id,
            source=data.get("source"),
            url=data.get("url"),
            title=data.get("title"),
        )
    return mid


def publish_message(
    chat_id: str,
    title: str,
    body: str,
    url: str,
    *,
    cfg=config,
    meta: Optional[Dict[str, Any]] = None,
) -> bool:
    if not chat_id:
        return False
    log.info("Публикация сообщения: chat_id=%s title=%s", chat_id, title)
    base = dict(meta or {})
    base.update({"title": title, "content": body, "url": url})
    mid = publish_structured_item(chat_id, base, cfg=cfg, rewrite_item=True)
    if mid:
        log.info("Сообщение опубликовано: chat_id=%s message_id=%s", chat_id, mid)
    else:
        log.error("Не удалось опубликовать сообщение: chat_id=%s title=%s", chat_id, title)
    return bool(mid)


# ---------------------------------------------------------------------------
# Moderation helpers
def send_moderation_preview(
    chat_id: str, item: Dict[str, Any], mod_id: int, cfg=config
) -> Optional[str]:
    log.info("Отправка предпросмотра модерации: chat_id=%s mod_id=%s", chat_id, mod_id)
    caption, long_text = format_preview(item, cfg)
    parse_mode = _normalize_parse_mode(
        getattr(cfg, "TELEGRAM_PARSE_MODE", getattr(cfg, "PARSE_MODE", "HTML"))
    )
    header = _build_moderation_header(mod_id, item)
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
                reply_to_message_id=mid if idx > 0 else None,
            )

        new_mid = _send_with_retry(_send, cfg)
        if not new_mid:
            log.error(
                "Не удалось отправить предпросмотр модерации: chat_id=%s mod_id=%s", chat_id, mod_id
            )
            audit(
                "moderation.preview_failure",
                chat_id=chat_id,
                mod_id=mod_id,
                item_id=item.get("id") or item.get("queue_id"),
            )
            return mid if mid else None
        if idx == 0:
            mid = new_mid
    if mid:
        log.info(
            "Предпросмотр модерации отправлен: chat_id=%s mod_id=%s message_id=%s",
            chat_id,
            mod_id,
            mid,
        )
        audit(
            "moderation.preview_success",
            chat_id=chat_id,
            mod_id=mod_id,
            message_id=mid,
            item_id=item.get("id") or item.get("queue_id"),
        )
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
    chat_id = getattr(cfg, "CHANNEL_CHAT_ID", "") or getattr(cfg, "CHANNEL_ID", "")
    if not chat_id:
        return None

    item_data = dict(row)
    item_data["content"] = text_override or row["content"] or ""
    mid = publish_structured_item(chat_id, item_data, cfg=cfg, rewrite_item=False)
    if not mid:
        return None

    conn.execute(
        "UPDATE moderation_queue SET status = ?, channel_message_id = ?, published_at = strftime('%s','now') WHERE id = ?",
        ("PUBLISHED", mid, mod_id),
    )
    conn.commit()
    return mid


class _BotApiAdapter:
    """Expose minimal Bot API surface for the new router publisher."""

    def __init__(self) -> None:
        self._dry_counter = 0

    def _call(self, method: str, payload: Dict[str, Any]) -> SimpleNamespace:
        if getattr(config, "DRY_RUN", False):
            self._dry_counter += 1
            message_id = f"dry-{self._dry_counter}"
            log.info(
                "[DRY-RUN] %s -> chat_id=%s length=%s",
                method,
                mask_secrets(str(payload.get("chat_id"))),
                len(str(payload.get("text") or payload.get("caption") or "")),
            )
            return SimpleNamespace(message_id=message_id)
        result = tg_api(method, **payload)
        if isinstance(result, dict):
            return SimpleNamespace(**result)
        return SimpleNamespace(message_id=result)

    def sendMessage(
        self,
        chat_id: str,
        text: str,
        parse_mode: Optional[str] = None,
        **kwargs: Any,
    ) -> SimpleNamespace:  # noqa: N802 - Telegram casing
        payload: Dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        payload.setdefault(
            "disable_web_page_preview",
            getattr(config, "TELEGRAM_DISABLE_WEB_PAGE_PREVIEW", False),
        )
        payload.update(kwargs)
        return self._call("sendMessage", payload)

    def sendPhoto(
        self,
        chat_id: str,
        photo: Any,
        caption: Optional[str] = None,
        parse_mode: Optional[str] = None,
        **kwargs: Any,
    ) -> SimpleNamespace:  # noqa: N802 - Telegram casing
        payload: Dict[str, Any] = {"chat_id": chat_id, "photo": photo}
        if caption is not None:
            payload["caption"] = caption
        if parse_mode:
            payload["parse_mode"] = parse_mode
        payload.update(kwargs)
        return self._call("sendPhoto", payload)

    def sendVideo(
        self,
        chat_id: str,
        video: Any,
        caption: Optional[str] = None,
        parse_mode: Optional[str] = None,
        **kwargs: Any,
    ) -> SimpleNamespace:  # noqa: N802 - Telegram casing
        payload: Dict[str, Any] = {"chat_id": chat_id, "video": video}
        if caption is not None:
            payload["caption"] = caption
        if parse_mode:
            payload["parse_mode"] = parse_mode
        payload.update(kwargs)
        return self._call("sendVideo", payload)


def publish_post(post: Dict[str, Any], *, is_raw: bool = False) -> None:
    """Publish a unified post into text and media channels."""

    if not post:
        log.warning("publish_post: пустой payload")
        return
    adapter = _BotApiAdapter()
    route_and_publish(adapter, post, is_raw=is_raw)


__all__ = [
    "init_telegram_client",
    "send_message",
    "publish_structured_item",
    "publish_message",
    "publish_raw",
    "tg_api",
    "split_html_message",
    "compose_preview",
    "format_preview",
    "send_moderation_preview",
    "publish_from_queue",
    "publish_post",
]

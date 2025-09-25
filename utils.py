# -*- coding: utf-8 -*-
import html
import hashlib
import re
from typing import Any, Dict
from urllib.parse import parse_qsl, urlparse, urlunparse, urlencode


def shorten_url(url: str, max_len: int = 100) -> str:
    """Возвращает укороченный вариант URL для логов."""
    try:
        if not url:
            return ""
        if len(url) <= max_len:
            return url
        return url[: max_len - 3] + "..."
    except Exception:
        return url

_WS_RE = re.compile(r"\s+", re.U)

def normalize_whitespace(text: str) -> str:
    if not isinstance(text, str):
        return ""
    return _WS_RE.sub(" ", text).strip()

_PUNCT_RE = re.compile(r"[^\w\s]+", re.U)
def compute_title_hash(title: str) -> str:
    """
    Нормализованный хеш заголовка (для поиска почти дублей).
    - в нижний регистр
    - убираем пунктуацию
    - схлопываем пробелы
    """
    base = normalize_whitespace(title).lower()
    base = _PUNCT_RE.sub(" ", base)
    base = normalize_whitespace(base)
    return hashlib.sha1(base.encode("utf-8")).hexdigest()

def safe_get(d: Dict[str, Any], key: str, default: str = "") -> str:
    v = d.get(key, default)
    return v if isinstance(v, str) else default


def canonicalize_url(url: str) -> str:
    """Normalize tracking parameters and fragments in URLs."""

    if not url:
        return ""

    try:
        parsed = urlparse(url, scheme="http")
    except Exception:
        return url

    scheme = parsed.scheme.lower() if parsed.scheme else "https"
    if scheme in {"", "http"}:
        scheme = "https"

    netloc = parsed.netloc or parsed.path
    path = parsed.path if parsed.netloc else ""
    if not netloc and parsed.hostname:
        netloc = parsed.hostname

    netloc = (netloc or "").lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    path = (path or "").rstrip("/") or "/"

    query_params = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not (k.lower().startswith("utm_") or k.lower() in {"yclid", "fbclid"})
    ]
    query = urlencode(query_params, doseq=True)

    return urlunparse((scheme, netloc, path, "", query, ""))


_MD_RESERVED = "_*[]()~`>#+-=|{}.!\\"


def _escape_for_mode(text: str, parse_mode: str) -> str:
    mode = (parse_mode or "HTML").strip().lower()
    if mode == "markdownv2":
        return "".join("\\" + ch if ch in _MD_RESERVED else ch for ch in text)
    if mode == "html":
        return html.escape(text)
    return text


def ensure_text_fits_parse_mode(
    text: str, max_chars: int, parse_mode: str, *, append_ellipsis: bool = True
) -> str:
    """Trim ``text`` so that escaped representation fits ``max_chars``.

    Telegram applies escaping depending on parse mode.  When we limit text by
    characters before escaping (например при рерайте), итоговое сообщение может
    оказаться длиннее лимита из‑за добавленных backslash/HTML сущностей.  Этот
    хелпер проверяет длину уже экранированного текста и при необходимости
    подрезает исходную строку, чтобы уложиться в лимит.
    """

    if not text:
        return ""
    if max_chars <= 0:
        return ""

    escaped = _escape_for_mode(text, parse_mode)
    if len(escaped) <= max_chars:
        return text

    ellipsis = "…" if append_ellipsis and max_chars > 1 else ""
    base_limit = max_chars - len(ellipsis)
    candidate = text.strip()

    while candidate:
        escaped_candidate = _escape_for_mode(candidate + ellipsis, parse_mode)
        if len(escaped_candidate) <= max_chars:
            return candidate + ellipsis
        # попробуем аккуратно убрать последнее слово
        trimmed = candidate.rsplit(" ", 1)[0].rstrip()
        if not trimmed or trimmed == candidate:
            candidate = candidate[:-1].rstrip()
        else:
            candidate = trimmed

    # если не удалось подобрать аккуратную обрезку, режем по символам
    hard_cut = text[: base_limit]
    return hard_cut + ellipsis if ellipsis else hard_cut

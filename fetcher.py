# -*- coding: utf-8 -*-
import time
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse

import feedparser
import requests

try:
    from . import config, net, dedup
    from .utils import canonicalize_url, normalize_whitespace, shorten_url
    from .parsers import html as html_parsers
except ImportError:  # pragma: no cover
    import config, net  # type: ignore
    import dedup  # type: ignore
    from utils import canonicalize_url, normalize_whitespace, shorten_url  # type: ignore
    html_parsers = None  # type: ignore

from logging_setup import get_logger

logger = get_logger(__name__)


try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:
    BeautifulSoup = None

_HOST_FAILS: Dict[str, float] = {}
_HOST_FAIL_STATS: Dict[str, Dict[str, float]] = {}
_HOST_QUARANTINE: Dict[str, float] = {}
_FAIL_TTL = 30 * 60  # 30 minutes
_HTTP_CACHE: Dict[str, Dict[str, str]] = {}

_MONTHS_RU = {
    "январ": 1,
    "феврал": 2,
    "март": 3,
    "апрел": 4,
    "май": 5,
    "мая": 5,
    "июн": 6,
    "июл": 7,
    "август": 8,
    "сентябр": 9,
    "октябр": 10,
    "ноябр": 11,
    "декабр": 12,
}


def _ensure_host_stats(host: str, now: Optional[float] = None) -> Dict[str, float]:
    stats = _HOST_FAIL_STATS.get(host)
    if stats is None:
        stats = {
            "count": 0,
            "total_failures": 0,
            "first_failure_ts": 0.0,
            "last_failure_ts": 0.0,
            "last_recovery_ts": 0.0,
            "recoveries": 0,
            "alerted_at": 0.0,
            "tls_dns_count": 0,
            "quarantined_until": 0.0,
            "last_quarantine_log": 0.0,
        }
        _HOST_FAIL_STATS[host] = stats
    if now is not None:
        stats["last_checked_ts"] = now
    return stats


def _record_host_failure(host: str, reason: str, *, now: Optional[float] = None) -> None:
    now = now or time.time()
    stats = _ensure_host_stats(host, now)
    stats["count"] = int(stats.get("count", 0)) + 1
    stats["total_failures"] = int(stats.get("total_failures", 0)) + 1
    if not stats.get("first_failure_ts"):
        stats["first_failure_ts"] = now
    stats["last_failure_ts"] = now

    if reason in {"dns", "tls"}:
        stats["tls_dns_count"] = int(stats.get("tls_dns_count", 0)) + 1
    else:
        stats["tls_dns_count"] = 0

    threshold = max(1, int(getattr(config, "HOST_FAIL_ALERT_THRESHOLD", 5)))
    window = max(0, int(getattr(config, "HOST_FAIL_ALERT_WINDOW_SEC", 1800)))
    cooldown = max(60, int(getattr(config, "HOST_FAIL_ALERT_COOLDOWN_SEC", 900)))

    if stats["count"] >= threshold:
        within_window = window <= 0 or (now - stats["first_failure_ts"]) <= window
        last_alert = stats.get("alerted_at", 0.0)
        if within_window and (now - last_alert) >= cooldown:
            logger.warning(
                "Источник %s недоступен %d раз подряд", host, stats["count"]
            )
            stats["alerted_at"] = now

    _maybe_auto_quarantine(host, stats, reason=reason, now=now)


def _record_host_success(host: str, *, now: Optional[float] = None) -> None:
    now = now or time.time()
    stats = _ensure_host_stats(host, now)
    if stats.get("count", 0):
        downtime = now - float(stats.get("first_failure_ts") or now)
        attempts = stats.get("count", 0)
        logger.info(
            "Источник %s восстановился после %d неудачных попыток за %.1f мин.",
            host,
            attempts,
            max(0.0, downtime / 60),
        )
        stats["recoveries"] = int(stats.get("recoveries", 0)) + 1
    stats["count"] = 0
    stats["first_failure_ts"] = 0.0
    stats["alerted_at"] = 0.0
    stats["last_recovery_ts"] = now
    stats["tls_dns_count"] = 0
    stats["quarantined_until"] = 0.0
    stats["last_quarantine_log"] = 0.0
    _HOST_QUARANTINE.pop(host, None)


def get_host_fail_stats(active_only: bool = False) -> Dict[str, Dict[str, float]]:
    """Return snapshot of host failure statistics."""

    out: Dict[str, Dict[str, float]] = {}
    for host, stats in _HOST_FAIL_STATS.items():
        if active_only and int(stats.get("count", 0)) <= 0:
            continue
        out[host] = dict(stats)
    return out


def reset_host_fail_stats() -> None:
    """Helper primarily for tests to reset failure accounting."""

    _HOST_FAILS.clear()
    _HOST_FAIL_STATS.clear()
    _HOST_QUARANTINE.clear()


def _quarantine_duration_seconds() -> float:
    default_hours = 4.0
    raw_hours = getattr(config, "HOST_FAIL_AUTO_QUARANTINE_HOURS", default_hours)
    try:
        hours = float(raw_hours)
    except (TypeError, ValueError):
        hours = default_hours
    hours = max(2.0, min(6.0, hours))
    return hours * 3600.0


def _notify_service_chat(message: str) -> None:
    chat_id = str(getattr(config, "SERVICE_CHAT_ID", "") or getattr(config, "ADMIN_CHAT_ID", "")).strip()
    if not chat_id:
        return
    token = getattr(config, "BOT_TOKEN", "").strip()
    if not token or getattr(config, "DRY_RUN", False):
        logger.debug("Пропущено уведомление в служебный чат: нет токена или DRY_RUN")
        return
    try:  # pragma: no cover - heavy dependency, not critical for tests
        from . import publisher  # type: ignore
    except ImportError:  # pragma: no cover - direct execution
        import publisher  # type: ignore
    try:
        publisher.send_message(str(chat_id), message, cfg=config)
    except Exception as exc:  # pragma: no cover - logging side effect
        logger.exception("Не удалось отправить уведомление в служебный чат: %s", exc)


def _list_source_names(host: str) -> List[str]:
    host = host.lower()
    names: List[str] = []
    sources = getattr(config, "SOURCES", []) or []
    for source in sources:
        url = str(source.get("url") or "").strip()
        domain = str(source.get("source_domain") or "").strip().lower()
        parsed_host = (urlparse(url).hostname or "").lower()
        if parsed_host.startswith("www."):
            parsed_host = parsed_host[4:]
        candidates = {host_part for host_part in (domain, parsed_host) if host_part}
        if host in candidates:
            name = str(source.get("name") or "").strip()
            if name:
                names.append(name)
    return names


def _maybe_auto_quarantine(host: str, stats: Dict[str, float], *, reason: str, now: float) -> None:
    if reason not in {"dns", "tls"}:
        return
    threshold = max(1, int(getattr(config, "HOST_FAIL_AUTO_QUARANTINE_THRESHOLD", 3)))
    if int(stats.get("tls_dns_count", 0)) < threshold:
        return

    until_existing = float(stats.get("quarantined_until", 0.0))
    if until_existing and until_existing > now:
        return

    duration = _quarantine_duration_seconds()
    until = now + duration
    _HOST_QUARANTINE[host] = until
    stats["quarantined_until"] = until
    stats["quarantined_at"] = now

    names = _list_source_names(host)
    hours = duration / 3600.0
    readable = ", ".join(names) if names else host
    message = (
        f"Источник {readable} автоматически отключён на {hours:.1f} ч из-за повторных "
        f"{reason.upper()}"
    )
    logger.warning("[AUTO-QUARANTINE] %s", message)
    _notify_service_chat(message)


def _active_quarantine_until(host: str, now: Optional[float] = None) -> float:
    now = now or time.time()
    until = float(_HOST_QUARANTINE.get(host, 0.0) or 0.0)
    if not until:
        return 0.0
    if until <= now:
        _HOST_QUARANTINE.pop(host, None)
        stats = _HOST_FAIL_STATS.get(host)
        if stats is not None:
            stats["quarantined_until"] = 0.0
        return 0.0
    return until


def _cache_key(url: str) -> str:
    key = canonicalize_url(url)
    return key or url


def _conditional_headers(url: str) -> Dict[str, str]:
    data = _HTTP_CACHE.get(_cache_key(url))
    if not data:
        return {}
    headers: Dict[str, str] = {}
    etag = data.get("etag")
    last_modified = data.get("last_modified")
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    return headers


def _store_response_headers(url: str, headers: Dict[str, str]) -> None:
    if not headers:
        return
    etag = headers.get("ETag") or headers.get("etag")
    last_modified = headers.get("Last-Modified") or headers.get("last-modified")
    if not etag and not last_modified:
        return
    key = _cache_key(url)
    _HTTP_CACHE[key] = {}
    if etag:
        _HTTP_CACHE[key]["etag"] = etag
    if last_modified:
        _HTTP_CACHE[key]["last_modified"] = last_modified


def _parse_datetime(value: str) -> Optional[datetime]:
    if not value:
        return None

    text = value.strip()
    if not text:
        return None

    lower = text.lower()
    now = datetime.now(timezone.utc)

    time_match = re.search(r"(\d{1,2}:\d{2})", lower)
    time_parts: Tuple[int, int] | None = None
    if time_match:
        try:
            hh, mm = time_match.group(1).split(":", 1)
            time_parts = (int(hh), int(mm))
        except Exception:
            time_parts = None

    if "сегодня" in lower:
        base = now
        if time_parts:
            base = base.replace(hour=time_parts[0], minute=time_parts[1], second=0, microsecond=0)
        return base
    if "вчера" in lower:
        base = now - timedelta(days=1)
        if time_parts:
            base = base.replace(hour=time_parts[0], minute=time_parts[1], second=0, microsecond=0)
        return base

    try:
        iso = text.replace("Z", "+00:00")
        return datetime.fromisoformat(iso)
    except Exception:
        pass

    try:
        return parsedate_to_datetime(text)
    except Exception:
        pass

    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue

    m = re.search(
        r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})(?:\s+г(?:ода)?)?(?:\s+(\d{1,2}:\d{2}))?",
        lower,
    )
    if m:
        day = int(m.group(1))
        month_txt = m.group(2)
        year = int(m.group(3))
        month = None
        for stem, num in _MONTHS_RU.items():
            if month_txt.startswith(stem):
                month = num
                break
        if month:
            hour = 0
            minute = 0
            if m.group(4):
                try:
                    hour, minute = map(int, m.group(4).split(":", 1))
                except Exception:
                    hour = minute = 0
            try:
                return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
            except ValueError:
                pass

    return None


def _is_recent(published_at: str) -> bool:
    days_back = int(getattr(config, "FETCH_DAYS_BACK", 7))
    if days_back <= 0:
        return True
    dt = _parse_datetime(published_at or "")
    if not dt:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(dt.tzinfo)
    return (now - dt) <= timedelta(days=days_back)


def _verify_for(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    bad = getattr(config, "SSL_NO_VERIFY_HOSTS", set())
    return host not in bad


def _first_http_url(candidates: Iterable[str]) -> str:
    """Return first URL starting with http(s) from iterable."""
    for url in candidates:
        if not url:
            continue
        url = url.strip()
        if url.startswith("http://") or url.startswith("https://"):
            return url
    return ""

# --- Мок-набор для локального теста ---
MOCK_ITEMS: List[Dict[str, str]] = [
    {
        "source": "MOCK",
        "guid": "mock-1",
        "url": "https://example.com/news/nn-construction-school",
        "title": "В Нижнем Новгороде началось строительство новой школы",
        "content": "Проект реализуется в рамках нацпрограммы. Подрядчик приступил к работам на площадке.",
        "published_at": "2025-09-04T10:00:00+03:00",
    },
    {
        "source": "MOCK",
        "guid": "mock-2",
        "url": "https://example.com/news/kazan-bridge",
        "title": "В Казани стартовало строительство моста",
        "content": "Работы начались на участке через реку, подрядчик определён.",
        "published_at": "2025-09-04T10:05:00+03:00",
    },
    {
        "source": "MOCK",
        "guid": "mock-3",
        "url": "https://example.com/news/nn-festival",
        "title": "В Нижнем Новгороде прошёл городской фестиваль",
        "content": "Жители посетили концерт и выставки на набережной.",
        "published_at": "2025-09-04T10:10:00+03:00",
    },
    {
        "source": "MOCK",
        "guid": "mock-4",
        "url": "https://example.com/news/nn-construction-school",
        "title": "Началось строительство школы в Нижнем Новгороде",
        "content": "Генподрядчик вывел технику, подготовительные работы начаты.",
        "published_at": "2025-09-04T10:15:00+03:00",
    },
    {
        "source": "MOCK",
        "guid": "mock-5",
        "url": "https://example.com/news/nn-school-project-started",
        "title": "Строительство школы стартовало в Нижнем Новгороде",
        "content": "Объект планируют сдать в 2026 году, предусмотрена инфраструктура.",
        "published_at": "2025-09-04T10:20:00+03:00",
    },
]

# -------------------- HTTP helpers --------------------

def _fetch_text(
    url: str,
    *,
    timeout: Optional[tuple[int, int]] = None,
    allow_redirects: bool = True,
) -> str:
    host = (urlparse(url).hostname or "").lower()
    now = time.time()
    quarantine_until = _active_quarantine_until(host, now)
    if quarantine_until:
        stats = _ensure_host_stats(host, now)
        stats["last_failure_ts"] = now
        logger.debug(
            "[SKIP_QUARANTINE] %s до %s", host, datetime.fromtimestamp(quarantine_until, tz=timezone.utc)
        )
        return ""
    if host in _HOST_FAILS and now - _HOST_FAILS[host] < _FAIL_TTL:
        stats = _HOST_FAIL_STATS.get(host)
        if stats is not None:
            stats["last_failure_ts"] = now
        return ""
    try:
        failure_reason = "other"
        read_to = timeout[1] if timeout else None
        verify = _verify_for(url)
        headers = _conditional_headers(url)
        text, resp_headers, status = net.get_text_with_meta(
            url,
            timeout=read_to,
            allow_redirects=allow_redirects,
            headers=headers or None,
            verify=verify,
        )
        _HOST_FAILS.pop(host, None)
        _record_host_success(host, now=now)
        if status == 304:
            return ""
        _store_response_headers(url, resp_headers)
        return text
    except requests.exceptions.SSLError as ex:
        logger.warning("TLS_FAIL %s: %s", host, ex)
        failure_reason = "tls"
    except requests.exceptions.ConnectionError as ex:
        logger.warning("DNS_FAIL %s: %s", host, ex)
        failure_reason = "dns"
    except Exception as ex:
        logger.debug("fetch error %s: %s", host, ex)
        failure_reason = "other"
    _HOST_FAILS[host] = now
    _record_host_failure(host, failure_reason, now=now)
    return ""

# -------------------- HTML article --------------------

def _extract_html_title(soup) -> str:
    if not soup: 
        return ""
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return normalize_whitespace(og["content"])
    if soup.title and soup.title.string:
        return normalize_whitespace(soup.title.string)
    h1 = soup.find("h1")
    if h1:
        return normalize_whitespace(h1.get_text(" ", strip=True))
    return ""

def _extract_html_published_at(soup) -> str:
    if not soup:
        return ""
    meta = soup.find("meta", attrs={"property": "article:published_time"})
    if meta and meta.get("content"):
        return meta["content"].strip()
    t = soup.find("time", attrs={"datetime": True})
    if t and t.get("datetime"):
        return t["datetime"].strip()
    # fallback: дата текстом у time/strong/em
    t2 = soup.find("time")
    if t2:
        return normalize_whitespace(t2.get_text(" ", strip=True))
    return ""

def _extract_html_content(soup) -> str:
    if not soup:
        return ""
    text_chunks: List[str] = []
    articles = soup.find_all("article") if soup else []
    if articles:
        for art in articles:
            for p in art.find_all("p"):
                txt = p.get_text(" ", strip=True)
                if txt: text_chunks.append(txt)
    else:
        # попытка вытянуть <div class="content|article|text|news">
        content_div = None
        for cls in ["content", "article", "news", "post", "entry", "text"]:
            content_div = soup.find("div", class_=lambda x: x and cls in x)
            if content_div: break
        nodes = (content_div.find_all("p") if content_div else soup.find_all("p"))
        for p in nodes[:80]:
            txt = p.get_text(" ", strip=True)
            if txt: text_chunks.append(txt)
    content = normalize_whitespace("\n\n".join(text_chunks))
    if len(content) > 8000:
        content = content[:8000].rsplit(" ", 1)[0].strip()
    return content


def _parse_html_article(
    source_name: str,
    url: str,
    *,
    timeout: Optional[tuple] = None,
    selectors: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, str]]:
    html_text = _fetch_text(url, timeout=timeout)
    if not html_text:
        return None
    title, content, published_at = "", "", ""
    lead_text = ""
    soup = None
    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(html_text, "html.parser")
            if selectors:
                title = title or _select_from_soup(soup, selectors.get("title"))
                lead_text = _select_from_soup(soup, selectors.get("lead"))
                date_sel = selectors.get("date") if isinstance(selectors, dict) else None
                if date_sel:
                    published_at = _select_date_from_soup(soup, date_sel)
                content = _extract_content_from_selectors(soup, selectors.get("content"))
            if not title:
                title = _extract_html_title(soup)
            if not published_at:
                published_at = _extract_html_published_at(soup)
            if not content:
                content = _extract_html_content(soup)
        except Exception as ex:
            logger.warning("Ошибка парсинга HTML (bs4) для %s: %s", url, ex)
            soup = None
    # грубые фолбэки
    if not title:
        try:
            import re
            m = re.search(r"<title[^>]*>(.*?)</title>", html_text, flags=re.I | re.S)
            if m:
                raw = m.group(1)
                raw = re.sub(r"\s+", " ", raw)
                title = normalize_whitespace(raw)
        except Exception:
            pass
    if not content and soup is not None:
        try:
            md = soup.find("meta", attrs={"name": "description"})
            if md and md.get("content"):
                content = normalize_whitespace(md["content"])
        except Exception:
            pass
    if not title:
        return None
    canon_url = canonicalize_url(url)
    item = {
        "source": source_name,
        "guid": canon_url or url,
        "url": canon_url or url,
        "title": title,
        "content": content,
        "published_at": published_at,
    }
    if lead_text:
        item["lead"] = lead_text
    return item

# -------------------- RSS --------------------

def _entry_to_item_rss(source_name: str, entry) -> Optional[Dict[str, str]]:
    link = getattr(entry, "link", "") or ""
    if not link:
        return None
    guid = getattr(entry, "id", "") or getattr(entry, "guid", "") or ""
    title = getattr(entry, "title", "") or ""
    published_at = getattr(entry, "published", "") or getattr(entry, "updated", "") or ""
    content_val = ""
    html_blobs: List[str] = []
    summary_raw = ""
    try:
        if getattr(entry, "content", None):
            blocks: List[str] = []
            for c in entry.content:
                val = getattr(c, "value", "") or ""
                if val:
                    blocks.append(val)
                    html_blobs.append(val)
            content_val = "\n\n".join(blocks)
        summary_raw = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
        if not content_val:
            content_val = summary_raw
    except Exception as ex:
        logger.debug("Не удалось разобрать контент RSS: %s", ex)

    if summary_raw:
        html_blobs.append(summary_raw)

    title = normalize_whitespace(title)
    content_val = normalize_whitespace(content_val)
    if not title:
        return None
    url_norm = canonicalize_url(link)
    guid_norm = guid.strip()
    if guid_norm.startswith("http") or guid_norm.startswith("//"):
        guid_norm = canonicalize_url(guid_norm)

    return {
        "source": source_name,
        "guid": guid_norm,
        "url": url_norm,
        "title": title,
        "content": content_val,
        "published_at": published_at,
    }

def fetch_rss(
    source: Dict[str, str],
    limit: int = 30,
    *,
    timeout: Optional[tuple] = None,
) -> List[Dict[str, str]]:
    url = source.get("url", "")
    name = source.get("name", "")
    if not url:
        return []
    logger.info("Загрузка RSS: %s (%s)", name, url)
    try:
        text = _fetch_text(url, timeout=timeout)
        if text is None:
            return []
        fp = feedparser.parse(text)
        items: List[Dict[str, str]] = []
        for e in fp.entries[:limit]:
            item = _entry_to_item_rss(name, e)
            if item:
                if not _is_recent(item.get("published_at") or ""):
                    logger.debug("[SKIP_OLD] %s %s", name, item.get("url"))
                    continue
                items.append(item)
        logger.info("Получено %d записей из RSS: %s", len(items), name)
        return items
    except Exception as ex:
        logger.exception("Ошибка RSS источника %s: %s", name, ex)
        return []

# -------------------- HTML single --------------------

def fetch_html(
    source: Dict[str, str], *, timeout: Optional[tuple] = None, domain_config: Optional[Dict[str, Any]] = None
) -> List[Dict[str, str]]:
    url = source.get("url", "")
    name = source.get("name", "")
    if not url:
        return []
    logger.info("Загрузка HTML: %s (%s)", name, url)
    try:
        selectors = None
        if domain_config:
            selectors = domain_config.get("article")
        item = _parse_html_article(name, url, timeout=timeout, selectors=selectors)
        return [item] if item else []
    except Exception as ex:
        logger.exception("Ошибка HTML источника %s: %s", name, ex)
        return []

# -------------------- HTML list (универсальный) --------------------

def _sel_many(root, css: Optional[str]):
    if not BeautifulSoup or not root:
        return []
    if not css:
        return []
    try:
        return root.select(css)
    except Exception:
        return []

def _text_or_empty(node) -> str:
    try:
        return normalize_whitespace(node.get_text(" ", strip=True))
    except Exception:
        return ""


def _ensure_iter(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if v]
    return [str(value)]


def _select_from_soup(soup, selectors: Any) -> str:
    for css in _ensure_iter(selectors):
        try:
            node = soup.select_one(css)
        except Exception:
            node = None
        if node:
            text = _text_or_empty(node)
            if text:
                return text
    return ""


def _extract_content_from_selectors(soup, selectors: Any) -> str:
    for css in _ensure_iter(selectors):
        try:
            container = soup.select_one(css)
        except Exception:
            container = None
        if not container:
            continue
        texts: List[str] = []
        for node in container.find_all(["p", "li"]):
            text = _text_or_empty(node)
            if text:
                texts.append(text)
        if texts:
            return "\n\n".join(texts)
        text = _text_or_empty(container)
        if text:
            return text
    return ""


def _select_date_from_soup(soup, config: Any) -> str:
    attr = "datetime"
    selectors = config
    if isinstance(config, dict):
        selectors = config.get("selectors") or config.get("css")
        attr = config.get("attr") or config.get("attribute") or attr
    for css in _ensure_iter(selectors):
        try:
            node = soup.select_one(css)
        except Exception:
            node = None
        if not node:
            continue
        if attr and getattr(node, "has_attr", None) and node.has_attr(attr):
            value = node.get(attr)
            if value:
                return normalize_whitespace(str(value))
        text = _text_or_empty(node)
        if text:
            return text
    return ""

def fetch_html_list(
    source: Dict[str, str],
    limit: int = 30,
    *,
    timeout: Optional[tuple] = None,
    domain_config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """
    Универсальный парсер листинга.
    Поддерживает произвольные селекторы из source['selectors'], но все поля опциональны.
    """
    base_url = source.get("url", "")
    name = source.get("name", "")
    if domain_config:
        sels = dict(domain_config.get("list", {}))
    else:
        sels = source.get("selectors") or {}
    if not base_url:
        return []
    if BeautifulSoup is None:
        logger.warning("beautifulsoup4 не установлен — html_list %s пропущен", name)
        return []

    logger.info("Загрузка HTML-листа: %s (%s)", name, base_url)
    html = _fetch_text(base_url, timeout=timeout)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")

    # 1) найдём карточки по селектору или эвристически
    items_nodes = _sel_many(soup, sels.get("item"))
    if not items_nodes:
        candidates = []
        for css in [
            "article",
            "div.news-item, div.news__item, div.article, div.post, div.entry, div.card",
            "li.news-item, li.post, li.entry",
            "div[class*='news']",
        ]:
            part = _sel_many(soup, css)
            if part:
                candidates.extend(part)
        items_nodes = candidates or soup.find_all("a")
    if not items_nodes:
        logger.warning(
            "Источник '%s': не найдено карточек (selectors=%s)",
            name,
            sels.get("item"),
        )

    out: List[Dict[str, str]] = []
    seen_links: set[str] = set()

    for node in items_nodes:
        if len(out) >= limit:
            break

        # 2) ссылка
        link_el = None
        link_css = sels.get("link") or "a"
        try:
            link_el = node.select_one(link_css) if hasattr(node, "select_one") else None
        except Exception:
            link_el = None
        if not link_el and hasattr(node, "find"):
            link_el = node.find("a")

        href = (link_el.get("href").strip() if link_el and link_el.get("href") else "")
        if not href:
            continue
        link_abs = canonicalize_url(urljoin(base_url, href))
        if link_abs in seen_links:
            continue
        seen_links.add(link_abs)

        # 3) заголовок (из листинга)
        title_el = None
        title_css = sels.get("title") or "h1 a, h2 a, h3 a, h1, h2, h3, a"
        try:
            title_el = node.select_one(title_css)
        except Exception:
            title_el = None
        title_list = _text_or_empty(title_el) if title_el else ""

        # 4) дата (если получится)
        date_text = ""
        date_css = sels.get("date") or "time, .date, .news-date, .posted-on"
        date_attr = (sels.get("date_attr") or "datetime").strip()
        date_el = None
        try:
            date_el = node.select_one(date_css)
        except Exception:
            date_el = None
        if date_el:
            date_text = date_el.get(date_attr) or _text_or_empty(date_el)

        lead_text = ""
        summary_css = sels.get("summary") or sels.get("lead")
        if summary_css:
            try:
                summary_el = node.select_one(summary_css)
            except Exception:
                summary_el = None
            if summary_el:
                lead_text = _text_or_empty(summary_el)

        # 5) загрузим карточку материала
        selectors_article = domain_config.get("article") if domain_config else None
        detail = _parse_html_article(
            name, link_abs, timeout=timeout, selectors=selectors_article
        )
        if not detail:
            if not _is_recent(date_text or ""):
                logger.debug("[SKIP_OLD] %s %s", name, link_abs)
                continue
            out.append({
                "source": name,
                "guid": link_abs,
                "url": link_abs,
                "title": title_list or "(без заголовка)",
                "content": lead_text or "",
                "published_at": date_text or "",
            })
            continue

        # финальный заголовок/контент
        title_final = detail.get("title") or title_list or ""
        content_final = detail.get("content") or lead_text or ""
        detail_url = canonicalize_url(detail.get("url") or link_abs)
        published_final = detail.get("published_at") or date_text or ""
        if not _is_recent(published_final):
            logger.debug("[SKIP_OLD] %s %s", name, detail_url)
            continue
        out.append({
            "source": name,
            "guid": detail.get("guid") or detail_url,
            "url": detail_url,
            "title": title_final,
            "content": content_final,
            "published_at": published_final,
        })

    logger.info("Получено %d записей из HTML-листа: %s", len(out), name)
    return out

# -------------------- MOCK --------------------

def fetch_mock(source: Dict[str, str]) -> List[Dict[str, str]]:
    logger.info("Используется мок-источник: %s", source.get("name", "MOCK"))
    return [dict(it) for it in MOCK_ITEMS]

# -------------------- Multiplexer --------------------

def fetch_all(
    sources: Iterable[Dict[str, str]],
    limit_per_source: Optional[int] = None,
) -> Iterator[Dict[str, str]]:
    """Yield items from all enabled sources one by one.

    Раньше функция возвращала список, и публикация начиналась лишь после
    обработки всех источников. Теперь элементы выдаются по мере получения,
    чтобы подходящие новости сразу отправлялись на модерацию.
    """
    limit = int(limit_per_source or getattr(config, "FETCH_LIMIT_PER_SOURCE", 30))
    sim_threshold = float(
        getattr(
            config,
            "BATCH_SIMILARITY_THRESHOLD",
            getattr(config, "CLUSTER_SIM_THRESHOLD", 0.85),
        )
    )
    batch_profiles: List[Tuple[set[str], set[str]]] = []
    for s in sources:
        if not s.get("enabled", True):
            logger.info("Источник '%s' отключен конфигом", s.get("name"))
            continue
        stype = (s.get("type") or "rss").strip().lower()
        timeout = s.get("timeout")
        domain_config = None
        source_url = s.get("url", "")
        parsed = urlparse(source_url)
        host = (parsed.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if not host:
            host = (s.get("source_domain") or "").strip().lower()
        quarantine_until = _active_quarantine_until(host) if host else 0.0
        if quarantine_until:
            stats = _ensure_host_stats(host)
            last_log = float(stats.get("last_quarantine_log", 0.0))
            now = time.time()
            if now - last_log > 60:
                until_dt = datetime.fromtimestamp(quarantine_until, tz=timezone.utc)
                logger.warning(
                    "Источник '%s' пропущен: автокарантин до %s",
                    s.get("name"),
                    until_dt.isoformat(),
                )
                stats["last_quarantine_log"] = now
            continue
        if html_parsers:
            domain_hint = s.get("source_domain")
            if not domain_hint:
                url = s.get("url", "")
                domain_hint = (urlparse(url).hostname or "").lower()
                if domain_hint.startswith("www."):
                    domain_hint = domain_hint[4:]
            if domain_hint:
                domain_config = html_parsers.get_domain_config(domain_hint)
        try:
            if stype == "html":
                if domain_config and domain_config.get("list"):
                    items = fetch_html_list(
                        s, limit=limit, timeout=timeout, domain_config=domain_config
                    )
                else:
                    items = fetch_html(
                        s, timeout=timeout, domain_config=domain_config
                    )
            elif stype == "html_list":
                items = fetch_html_list(
                    s, limit=limit, timeout=timeout, domain_config=domain_config
                )
            elif stype == "mock":
                items = fetch_mock(s)
            else:
                items = fetch_rss(s, limit=limit, timeout=timeout)

            for it in items:
                title = it.get("title") or ""
                similar, profile = dedup.similar_to_any(
                    title, batch_profiles, threshold=sim_threshold
                )
                if similar:
                    logger.debug(
                        "[SKIP_SIMILAR] %s | %s",
                        s.get("name"),
                        title[:160],
                    )
                    continue
                batch_profiles.append(profile)
                yield it
            time.sleep(0.2)
        except Exception as ex:
            logger.exception("Необработанная ошибка источника %s: %s", s, ex)


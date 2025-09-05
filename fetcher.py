# -*- coding: utf-8 -*-
import logging
import time
import re
from typing import Dict, Iterable, List, Optional
from urllib.parse import urljoin

import requests
import feedparser

from . import config
from .utils import normalize_whitespace

logger = logging.getLogger(__name__)

try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:
    BeautifulSoup = None


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
    {"source":"MOCK","guid":"mock-1","url":"https://example.com/news/nn-construction-school","title":"В Нижнем Новгороде началось строительство новой школы","content":"Проект реализуется в рамках нацпрограммы. Подрядчик приступил к работам на площадке.","published_at":"2025-09-04T10:00:00+03:00"},
    {"source":"MOCK","guid":"mock-2","url":"https://example.com/news/kazan-bridge","title":"В Казани стартовало строительство моста","content":"Работы начались на участке через реку, подрядчик определён.","published_at":"2025-09-04T10:05:00+03:00"},
    {"source":"MOCK","guid":"mock-3","url":"https://example.com/news/nn-festival","title":"В Нижнем Новгороде прошёл городской фестиваль","content":"Жители посетили концерт и выставки на набережной.","published_at":"2025-09-04T10:10:00+03:00"},
    {"source":"MOCK","guid":"mock-4","url":"https://example.com/news/nn-construction-school","title":"Началось строительство школы в Нижнем Новгороде","content":"Генподрядчик вывел технику, подготовительные работы начаты.","published_at":"2025-09-04T10:15:00+03:00"},
    {"source":"MOCK","guid":"mock-5","url":"https://example.com/news/nn-school-project-started","title":"Строительство школы стартовало в Нижнем Новгороде","content":"Объект планируют сдать в 2026 году, предусмотрена инфраструктура.","published_at":"2025-09-04T10:20:00+03:00"},
]

# -------------------- HTTP helpers --------------------

def _requests_get(url: str, timeout: int = 20) -> Optional[str]:
    headers = {
        "User-Agent": "newsbot/1.0 (+https://example.com)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        r.encoding = r.encoding or "utf-8"
        return r.text
    except Exception as ex:
        logger.warning("Ошибка HTTP при загрузке %s: %s", url, ex)
        return None

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

def _extract_html_image_url(soup) -> str:
    if not soup:
        return ""
    # meta tags: OpenGraph and Twitter cards
    for attrs in [
        {"property": "og:image"},
        {"property": "og:image:url"},
        {"name": "twitter:image"},
        {"name": "twitter:image:src"},
        {"property": "twitter:image"},
        {"property": "twitter:image:src"},
    ]:
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            return tag["content"].strip()
    # link rel="image_src"
    link = soup.find("link", attrs={"rel": "image_src"})
    if link and link.get("href"):
        return link["href"].strip()
    # first <img>
    img = soup.find("img")
    if img and img.get("src"):
        return img["src"].strip()
    return ""

def _parse_html_article(source_name: str, url: str) -> Optional[Dict[str, str]]:
    html_text = _requests_get(url)
    if not html_text:
        return None
    title, content, published_at, image_url = "", "", "", ""
    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(html_text, "html.parser")
            title = _extract_html_title(soup)
            published_at = _extract_html_published_at(soup)
            content = _extract_html_content(soup)
            img = _extract_html_image_url(soup)
            if img:
                image_url = urljoin(url, img)
        except Exception as ex:
            logger.warning("Ошибка парсинга HTML (bs4) для %s: %s", url, ex)
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
    if not content and BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(html_text, "html.parser")
            md = soup.find("meta", attrs={"name": "description"})
            if md and md.get("content"):
                content = normalize_whitespace(md["content"])
        except Exception:
            pass
    if not title:
        return None
    return {
        "source": source_name,
        "guid": url,
        "url": url,
        "title": title,
        "content": content,
        "published_at": published_at,
        "image_url": image_url,
    }

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
    try:
        if getattr(entry, "content", None):
            blocks = []
            for c in entry.content:
                val = getattr(c, "value", "") or ""
                if val:
                    blocks.append(val)
                    html_blobs.append(val)
            content_val = "\n\n".join(blocks)
        summary_raw = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
        if not content_val:
            content_val = summary_raw
        if summary_raw:
            html_blobs.append(summary_raw)
    except Exception:
        pass
    candidates: List[str] = []
    for m in getattr(entry, "media_content", []) or []:
        url = getattr(m, "url", "") or (m.get("url") if isinstance(m, dict) else "")
        if url:
            candidates.append(url)
    for m in getattr(entry, "media_thumbnail", []) or []:
        url = getattr(m, "url", "") or (m.get("url") if isinstance(m, dict) else "")
        if url:
            candidates.append(url)
    for en in getattr(entry, "enclosures", []) or []:
        url = getattr(en, "href", "") or getattr(en, "url", "")
        if isinstance(en, dict):
            url = en.get("href") or en.get("url") or url
        if url:
            candidates.append(url)
    for ln in getattr(entry, "links", []) or []:
        rel = getattr(ln, "rel", "") or (ln.get("rel") if isinstance(ln, dict) else "")
        type_ = getattr(ln, "type", "") or (ln.get("type") if isinstance(ln, dict) else "")
        href = getattr(ln, "href", "") or getattr(ln, "url", "")
        if isinstance(ln, dict):
            href = ln.get("href") or ln.get("url") or href
        if rel == "enclosure" and type_.startswith("image/") and href:
            candidates.append(href)
    img_re = re.compile(r'''<img[^>]+src=['"]([^'"]+)['"]''', flags=re.I)
    for blob in html_blobs:
        for img in img_re.findall(blob):
            candidates.append(img)
    image_url = _first_http_url(candidates)
    title = normalize_whitespace(title)
    content_val = normalize_whitespace(content_val)
    if not title:
        return None
    return {
        "source": source_name,
        "guid": guid,
        "url": link,
        "title": title,
        "content": content_val,
        "published_at": published_at,
        "image_url": image_url,
    }

def fetch_rss(source: Dict[str, str], limit: int = 30) -> List[Dict[str, str]]:
    url = source.get("url", "")
    name = source.get("name", "")
    if not url:
        return []
    logger.info("Загрузка RSS: %s (%s)", name, url)
    try:
        fp = feedparser.parse(url)
        items: List[Dict[str, str]] = []
        for e in fp.entries[:limit]:
            item = _entry_to_item_rss(name, e)
            if item:
                items.append(item)
        logger.info("Получено %d записей из RSS: %s", len(items), name)
        return items
    except Exception as ex:
        logger.exception("Ошибка RSS источника %s: %s", name, ex)
        return []

# -------------------- HTML single --------------------

def fetch_html(source: Dict[str, str]) -> List[Dict[str, str]]:
    url = source.get("url", "")
    name = source.get("name", "")
    if not url:
        return []
    logger.info("Загрузка HTML: %s (%s)", name, url)
    try:
        item = _parse_html_article(name, url)
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

def fetch_html_list(source: Dict[str, str], limit: int = 30) -> List[Dict[str, str]]:
    """
    Универсальный парсер листинга.
    Поддерживает произвольные селекторы из source['selectors'], но все поля опциональны.
    """
    base_url = source.get("url", "")
    name = source.get("name", "")
    sels = source.get("selectors") or {}
    if not base_url:
        return []
    if BeautifulSoup is None:
        logger.warning("beautifulsoup4 не установлен — html_list %s пропущен", name)
        return []

    logger.info("Загрузка HTML-листа: %s (%s)", name, base_url)
    html = _requests_get(base_url)
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
        link_abs = urljoin(base_url, href)
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

        # 5) загрузим карточку материала
        detail = _parse_html_article(name, link_abs)
        if not detail:
            out.append({
                "source": name,
                "guid": link_abs,
                "url": link_abs,
                "title": title_list or "(без заголовка)",
                "content": "",
                "published_at": date_text or "",
            })
            continue

        # финальный заголовок/контент
        title_final = detail.get("title") or title_list or ""
        out.append({
            "source": name,
            "guid": detail.get("guid") or link_abs,
            "url": detail.get("url") or link_abs,
            "title": title_final,
            "content": detail.get("content") or "",
            "published_at": detail.get("published_at") or date_text or "",
        })

    logger.info("Получено %d записей из HTML-листа: %s", len(out), name)
    return out

# -------------------- MOCK --------------------

def fetch_mock(source: Dict[str, str]) -> List[Dict[str, str]]:
    logger.info("Используется мок-источник: %s", source.get("name", "MOCK"))
    return [dict(it) for it in MOCK_ITEMS]

# -------------------- Multiplexer --------------------

def fetch_all(sources: Iterable[Dict[str, str]], limit_per_source: Optional[int] = None) -> List[Dict[str, str]]:
    limit = int(limit_per_source or getattr(config, "FETCH_LIMIT_PER_SOURCE", 30))
    result: List[Dict[str, str]] = []
    for s in sources:
        stype = (s.get("type") or "rss").strip().lower()
        try:
            if stype == "html":
                result.extend(fetch_html(s))
            elif stype == "html_list":
                result.extend(fetch_html_list(s, limit=limit))
            elif stype == "mock":
                result.extend(fetch_mock(s))
            else:
                result.extend(fetch_rss(s, limit=limit))
            time.sleep(0.2)
        except Exception as ex:
            logger.exception("Необработанная ошибка источника %s: %s", s, ex)
    return result

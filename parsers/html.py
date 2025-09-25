from __future__ import annotations

from typing import Any, Dict, List
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from utils import normalize_whitespace

DOMAIN_CONFIG: Dict[str, Dict[str, Any]] = {
    "minstroy.nobl.ru": {
        "article": {
            "title": ["h1", ".page-title"],
            "lead": [".intro", ".lead"],
            "date": {"selectors": ["time[datetime]", ".article-date"], "attr": "datetime"},
            "content": ["article", ".article-body"],
        },
        "list": {
            "item": "article, .news-item",
            "link": "a",
            "title": [".news-title", "h2", "a"],
            "summary": [".news-preview", ".lead"],
            "date": {"selectors": ["time", ".date"], "attr": "datetime"},
        },
    },
    "mingrad.nobl.ru": {
        "article": {
            "title": ["h1", ".post-title"],
            "lead": [".intro", ".lead"],
            "date": {"selectors": ["time[datetime]", ".news-date"], "attr": "datetime"},
            "content": ["article", ".post-content"],
        },
        "list": {
            "item": "article, .news-item",
            "link": "a",
            "title": [".news-title", "h2", "a"],
            "summary": [".news-preview", ".lead"],
            "date": {"selectors": ["time", ".date"], "attr": "datetime"},
        },
    },
    "newsnn.ru": {
        "article": {
            "title": ["h1", ".article__title"],
            "lead": [".article__lead", ".article-lead"],
            "date": {"selectors": ["time", ".article__date"], "attr": "datetime"},
            "content": [".article__body", ".article-body"],
        },
    },
    "nn.ru": {
        "article": {
            "title": ["h1", ".article__title"],
            "lead": [".article__lead", ".article-intro"],
            "date": {"selectors": ["time", ".article__date"], "attr": "datetime"},
            "content": [".article__text", ".article-body"],
        },
    },
    "domostroynn.ru": {
        "article": {
            "title": ["h1", ".news-detail__title"],
            "lead": [".news-detail__lead"],
            "date": {"selectors": ["time", ".news-detail__date"], "attr": "datetime"},
            "content": [".news-detail__content", "article"],
        },
    },
    "kommersant.ru": {
        "article": {
            "title": ["h1", ".article_name"],
            "lead": [".article_subheader", ".article__lead"],
            "date": {"selectors": ["time", ".article_dater"], "attr": "datetime"},
            "content": [".article_text", ".article__text"],
        },
    },
    "nn.rbc.ru": {
        "article": {
            "title": ["h1", ".article__header"],
            "lead": [".article__subtitle", ".article__lead"],
            "date": {"selectors": ["time", ".article__date"], "attr": "datetime"},
            "content": [".article__content", ".l-col-main"],
        },
    },
    "vgoroden.ru": {
        "article": {
            "title": ["h1", ".article-title"],
            "lead": [".article-lead", ".article-intro"],
            "date": {"selectors": ["time", ".article-date"], "attr": "datetime"},
            "content": [".article-body", ".article__content"],
        },
    },
    "nta-pfo.ru": {
        "article": {
            "title": ["h1", ".news-detail__title"],
            "lead": [".news-detail__lead"],
            "date": {"selectors": ["time", ".news-detail__date"], "attr": "datetime"},
            "content": [".news-detail__content", "article"],
        },
    },
    "gipernn.ru": {
        "article": {
            "title": ["h1", ".article__title"],
            "lead": [".article__lead", ".article-intro"],
            "date": {"selectors": ["time", ".article__date"], "attr": "datetime"},
            "content": [".article__content", ".article-body"],
        },
    },
    "admgor.nnov.ru": {
        "article": {
            "title": ["h1", ".article-title", ".news-detail__title"],
            "lead": [".lead", ".intro", ".article-lead"],
            "date": {"selectors": ["time[datetime]", ".news-date", ".article-date"], "attr": "datetime"},
            "content": [".article-body", ".news-detail__content", "article"],
        },
    },
    "gsn.nobl.ru": {
        "article": {
            "title": ["h1", ".article-title", ".news-detail__title"],
            "lead": [".intro", ".lead", ".news-detail__lead"],
            "date": {"selectors": ["time[datetime]", ".news-date", ".article-date"], "attr": "datetime"},
            "content": [".article-body", ".news-detail__content", "article"],
        },
    },
    "52.mchs.gov.ru": {
        "article": {
            "title": ["h1", ".article__title", ".news-detail__title"],
            "lead": [".article__lead", ".lead", ".intro"],
            "date": {"selectors": ["time[datetime]", ".news-date", ".article-date"], "attr": "datetime"},
            "content": [".article__content", ".article-body", "article"],
        },
    },
    "strategy.nobl.ru": {
        "article": {
            "title": ["h1", ".article-title", ".news-detail__title"],
            "lead": [".lead", ".intro", ".article-lead"],
            "date": {"selectors": ["time[datetime]", ".news-date", ".article-date"], "attr": "datetime"},
            "content": [".article-body", ".news-detail__content", "article"],
        },
    },
    "nizhstat.gks.ru": {
        "article": {
            "title": ["h1", ".article-title", ".news-detail__title"],
            "lead": [".lead", ".intro", ".article-lead"],
            "date": {"selectors": ["time[datetime]", ".news-date", ".article-date"], "attr": "datetime"},
            "content": [".article-body", ".news-detail__content", "article"],
        },
    },
    "vremyan.ru": {
        "article": {
            "title": ["h1", ".article-title"],
            "lead": [".article-lead", ".article-intro"],
            "date": {"selectors": ["time", ".article-date"], "attr": "datetime"},
            "content": [".article-body", ".article__content"],
        },
    },
}


def _ensure_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if v]
    return [str(value)]


def _select_text(node, selectors: Any) -> str:
    for css in _ensure_list(selectors):
        try:
            found = node.select_one(css)
        except Exception:
            found = None
        if found:
            text = normalize_whitespace(found.get_text(" ", strip=True))
            if text:
                return text
    return ""


def _select_date(node, selectors: Any, attr: str = "datetime") -> str:
    if isinstance(selectors, dict):
        attr = selectors.get("attr") or selectors.get("attribute") or attr
        selectors = selectors.get("selectors") or selectors.get("css")
    for css in _ensure_list(selectors):
        try:
            found = node.select_one(css)
        except Exception:
            found = None
        if not found:
            continue
        if attr and getattr(found, "has_attr", None) and found.has_attr(attr):
            value = found.get(attr)
            if value:
                return normalize_whitespace(str(value))
        text = normalize_whitespace(found.get_text(" ", strip=True))
        if text:
            return text
    return ""


def _collect_content(node, selectors: Any) -> str:
    for css in _ensure_list(selectors):
        try:
            container = node.select_one(css)
        except Exception:
            container = None
        if not container:
            continue
        parts: List[str] = []
        for child in container.find_all(["p", "li"]):
            text = normalize_whitespace(child.get_text(" ", strip=True))
            if text:
                parts.append(text)
        if parts:
            return "\n\n".join(parts)
        text = normalize_whitespace(container.get_text(" ", strip=True))
        if text:
            return text
    return ""


def get_domain_config(domain: str) -> Dict[str, Any]:
    key = (domain or "").lower().strip()
    if key.startswith("www."):
        key = key[4:]
    return DOMAIN_CONFIG.get(key, {})


def parse_article(html: str, domain: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    cfg = get_domain_config(domain).get("article", {})
    title = _select_text(soup, cfg.get("title")) or _select_text(soup, "h1")
    lead = _select_text(soup, cfg.get("lead"))
    published_at = _select_date(soup, cfg.get("date"))
    content = _collect_content(soup, cfg.get("content"))
    if not content:
        content = _collect_content(soup, ["article", "body"])
    return {
        "title": title or "",
        "lead": lead or "",
        "content": content or "",
        "published_at": published_at or "",
    }


def parse_listing(html: str, base_url: str, domain: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    cfg = get_domain_config(domain).get("list", {})
    item_selector = cfg.get("item") or "article, .news-item, .card"
    items = soup.select(item_selector)
    results: List[Dict[str, str]] = []
    for node in items:
        link_sel = cfg.get("link") or "a"
        try:
            link_el = node.select_one(link_sel)
        except Exception:
            link_el = None
        if not link_el or not link_el.get("href"):
            continue
        href = link_el.get("href")
        url = urljoin(base_url, href)
        title = _select_text(node, cfg.get("title") or link_sel)
        summary = _select_text(node, cfg.get("summary") or cfg.get("lead"))
        date_cfg = cfg.get("date")
        date_text = _select_date(node, date_cfg, attr="datetime") if date_cfg else ""
        results.append(
            {
                "url": url,
                "title": title or "",
                "summary": summary or "",
                "published_at": date_text or "",
            }
        )
    return results


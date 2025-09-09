from __future__ import annotations

import json
import re
from html import unescape
from typing import List
from urllib.parse import urljoin

from rewriter.base import NewsItem

# regexes for various sources
_META_OG = re.compile(r'<meta[^>]+?property="og:image"[^>]+?content="([^"]+)"', re.I)
_META_OG_SEC = re.compile(r'<meta[^>]+?property="og:image:secure_url"[^>]+?content="([^"]+)"', re.I)
_META_TW = re.compile(r'<meta[^>]+?name="twitter:image"[^>]+?content="([^"]+)"', re.I)
_JSON_LD_RE = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.I | re.S)
_IMG_RE = re.compile(
    r'<img[^>]+(?:src|data-src|data-original|data-lazy)=["\']([^"\']+)["\']',
    re.I,
)
_SRCSET_RE = re.compile(
    r'<(?:img|source)[^>]+(?:srcset|data-srcset)=["\']([^"\']+)["\']',
    re.I,
)

_PLACEHOLDER_RE = re.compile(
    r"(no[-_]?image|placeholder|plug|zaglushka|stub|default|spacer|1x1)",
    re.I,
)


def _best_from_srcset(srcset: str) -> str | None:
    """Return URL with largest width from srcset string."""
    best_url = None
    best_w = -1
    for part in srcset.split(','):
        part = part.strip()
        if not part:
            continue
        url, *rest = part.split()
        width = 0
        if rest:
            m = re.search(r"(\d+)(w|x)", rest[0])
            if m:
                width = int(m.group(1))
        if width > best_w:
            best_w = width
            best_url = url
    return best_url


def _json_ld_image_urls(block: str) -> List[str]:
    urls: List[str] = []
    try:
        data = json.loads(unescape(block))
    except Exception:
        return urls

    def _extract(obj):
        if isinstance(obj, str):
            urls.append(obj)
        elif isinstance(obj, list):
            for it in obj:
                _extract(it)
        elif isinstance(obj, dict):
            for key in ("image", "thumbnailUrl", "url", "@id"):
                if key in obj:
                    _extract(obj[key])
    _extract(data)
    return urls


def extract_image_urls(item: NewsItem) -> List[str]:
    """Extract candidate image URLs from ``item`` ordered by priority."""
    out: List[str] = []
    html = unescape(item.html or "")

    # meta tags in priority
    for rx in (_META_OG, _META_OG_SEC, _META_TW):
        out.extend(rx.findall(html))

    # JSON-LD blocks
    for block in _JSON_LD_RE.findall(html):
        out.extend(_json_ld_image_urls(block))

    # <picture>/<img> with srcset
    for srcset in _SRCSET_RE.findall(html):
        best = _best_from_srcset(srcset)
        if best:
            out.append(best)

    # <img> with various attributes
    out.extend(_IMG_RE.findall(html))

    # normalize and filter placeholders
    seen = set()
    final: List[str] = []
    for url in out:
        if not url:
            continue
        if item.url:
            url = urljoin(item.url, url)
        if url in seen:
            continue
        if _PLACEHOLDER_RE.search(url):
            continue
        seen.add(url)
        final.append(url)
    return final

from __future__ import annotations

import re
from html import unescape
from typing import List
from urllib.parse import urljoin

from rewriter.base import NewsItem

_META_RE = re.compile(r'<meta[^>]+?(?:property|name)="(?:og:image|twitter:image)"[^>]+?content="([^"]+)"', re.I)
_IMG_RE = re.compile(
    r'<img[^>]+(?:src|data-src|data-original)=["\']([^"\']+)["\']', re.I
)
_SRCSET_RE = re.compile(r'<(?:img|source)[^>]+srcset=["\']([^"\']+)["\']', re.I)


def extract_image_urls(item: NewsItem) -> List[str]:
    urls: List[str] = []
    if item.images:
        urls.extend(item.images)
    if item.html:
        html = unescape(item.html)
        urls.extend(_META_RE.findall(html))
        urls.extend(_IMG_RE.findall(html))
        for srcset in _SRCSET_RE.findall(html):
            first = srcset.split(",")[0].strip().split(" ")[0]
            if first:
                urls.append(first)
    seen = set()
    out: List[str] = []
    for u in urls:
        if not u:
            continue
        if item.url:
            u = urljoin(item.url, u)
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out

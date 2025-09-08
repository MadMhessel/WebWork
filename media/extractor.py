from __future__ import annotations

import re
from html import unescape
from typing import List

from rewriter.base import NewsItem

_META_RE = re.compile(r'<meta[^>]+?(?:property|name)="(?:og:image|twitter:image)"[^>]+?content="([^"]+)"', re.I)
_IMG_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.I)


def extract_image_urls(item: NewsItem) -> List[str]:
    urls: List[str] = []
    if item.images:
        urls.extend(item.images)
    if item.html:
        html = unescape(item.html)
        urls.extend(_META_RE.findall(html))
        urls.extend(_IMG_RE.findall(html))
    seen = set()
    out: List[str] = []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out

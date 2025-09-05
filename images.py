from __future__ import annotations
import hashlib
import logging
import os
import re
from dataclasses import dataclass
from io import BytesIO
from typing import List, Optional
from urllib.parse import urlparse

try:  # Pillow is optional during runtime
    from PIL import Image  # type: ignore
except Exception:  # pragma: no cover
    Image = None  # type: ignore

from . import config
from .fetcher import HTTP_SESSION, DEFAULT_TIMEOUT

log = logging.getLogger(__name__)

# simple in-memory cache: image_hash -> tg_file_id
images_cache: dict[str, str] = {}


@dataclass
class ImageCandidate:
    url: str


def extract_candidates(item: dict) -> List[ImageCandidate]:
    """Extract potential image URLs from item dict."""
    urls: List[str] = []
    u0 = item.get("image_url")
    if u0:
        urls.append(u0)
    content = item.get("content") or ""
    for u in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', content, flags=re.I):
        urls.append(u)
    seen: set[str] = set()
    out: List[ImageCandidate] = []
    for u in urls:
        if not u or u in seen:
            continue
        seen.add(u)
        if _url_allowed(u):
            out.append(ImageCandidate(url=u))
    return out


def _url_allowed(url: str) -> bool:
    """Filter URL by scheme, denylist patterns and extension."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    low = url.lower()
    deny = getattr(config, "IMAGE_DENYLIST_DOMAINS", set())
    if any(d in low for d in deny):
        return False
    ext = os.path.splitext(parsed.path)[1].lower()
    allowed_ext = getattr(config, "IMAGE_ALLOWED_EXT", set())
    if allowed_ext and ext not in allowed_ext:
        return False
    return True


def _domain_allowed(url: str) -> bool:
    allowed = getattr(config, "IMAGE_ALLOWED_DOMAINS", set())
    if not allowed:
        return True
    try:
        host = urlparse(url).hostname or ""
        return host.lower() in allowed
    except Exception:
        return False


def pick_best(candidates: List[ImageCandidate]) -> Optional[ImageCandidate]:
    """Pick first candidate matching domain whitelist."""
    for cand in candidates:
        if _domain_allowed(cand.url):
            return cand
    return None


def ensure_tg_file_id(image_url: str) -> Optional[str]:
    """Ensure Telegram file id for image, applying filters and caching by hash."""
    if not image_url or not getattr(config, "ALLOW_IMAGES", True):
        return None
    try:
        # HEAD check for type and length
        head = HTTP_SESSION.head(image_url, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
        ctype = head.headers.get("Content-Type", "")
        if head.status_code != 200 or not ctype.startswith("image/"):
            return None
        clen = int(head.headers.get("Content-Length", "0") or "0")
        if clen < int(getattr(config, "MIN_IMAGE_BYTES", 0)):
            return None
        r = HTTP_SESSION.get(image_url, timeout=DEFAULT_TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.content
        if len(data) < int(getattr(config, "MIN_IMAGE_BYTES", 0)):
            return None
        if Image is None:
            return image_url
        with Image.open(BytesIO(data)) as im:
            w, h = im.size
        if (
            w < int(getattr(config, "IMAGE_MIN_EDGE", 0))
            or h < int(getattr(config, "IMAGE_MIN_EDGE", 0))
            or w * h < int(getattr(config, "IMAGE_MIN_AREA", 0))
        ):
            return None
        ratio = w / float(h or 1)
        min_ratio = float(getattr(config, "IMAGE_MIN_RATIO", 0.0))
        max_ratio = float(getattr(config, "IMAGE_MAX_RATIO", 10.0))
        if ratio < min_ratio or ratio > max_ratio:
            return None
        ihash = hashlib.sha256(data).hexdigest()
        cached = images_cache.get(ihash)
        if cached:
            return cached
        images_cache[ihash] = image_url
        return image_url
    except Exception as ex:  # pragma: no cover
        log.debug("ensure_tg_file_id failed for %s: %s", image_url, ex)
        return None

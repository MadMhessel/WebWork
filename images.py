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

import sqlite3
from collections import Counter
from . import config, db, http_client

HTTP_SESSION = http_client.get_session()

log = logging.getLogger(__name__)

# simple in-memory cache: image_hash -> tg_file_id
images_cache: dict[str, str] = {}
image_stats = {"with_image": 0, "reasons": Counter()}


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
        if is_reasonable_image_url(u):
            out.append(ImageCandidate(url=u))
    return out


def is_reasonable_image_url(url: str) -> bool:
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


def ensure_tg_file_id(image_url: str, conn: Optional[sqlite3.Connection] = None) -> Optional[tuple[str, str]]:
    """Ensure Telegram file id for image, applying filters and caching by hash.

    Returns tuple ``(file_id, image_hash)`` or ``None`` if validation fails.
    Results are cached in the ``images_cache`` table when ``conn`` is provided.
    """
    if not image_url or not getattr(config, "ALLOW_IMAGES", True):
        return None

    if conn is None:
        try:
            conn = db.connect()
        except Exception:  # pragma: no cover
            conn = None

    if conn is not None:
        cur = conn.execute(
            "SELECT tg_file_id, hash FROM images_cache WHERE src_url = ?",
            (image_url,),
        )
        row = cur.fetchone()
        if row:
            return row["tg_file_id"], row["hash"]

    session = HTTP_SESSION
    try:
        head = session.head(image_url, timeout=(config.HTTP_TIMEOUT_CONNECT, config.HTTP_TIMEOUT_READ), allow_redirects=True)
        try:
            ctype = head.headers.get("Content-Type", "")
            if head.status_code != 200 or not ctype.startswith("image/"):
                image_stats["reasons"]["invalid_content_type"] += 1
                return None
            clen = int(head.headers.get("Content-Length", "0") or "0")
            if clen < int(getattr(config, "MIN_IMAGE_BYTES", 0)):
                image_stats["reasons"]["too_small"] += 1
                return None
        finally:
            if hasattr(head, "close"):
                head.close()
        r = session.get(image_url, timeout=(config.HTTP_TIMEOUT_CONNECT, config.HTTP_TIMEOUT_READ))
        try:
            if r.status_code != 200:
                image_stats["reasons"][str(r.status_code)] += 1
                return None
            data = r.content
            if len(data) < int(getattr(config, "MIN_IMAGE_BYTES", 0)):
                image_stats["reasons"]["too_small"] += 1
                return None
        finally:
            if hasattr(r, "close"):
                r.close()
        if Image is None:
            return None
        with Image.open(BytesIO(data)) as im:
            w, h = im.size
        if (
            w < int(getattr(config, "IMAGE_MIN_EDGE", 0))
            or h < int(getattr(config, "IMAGE_MIN_EDGE", 0))
            or w * h < int(getattr(config, "IMAGE_MIN_AREA", 0))
        ):
            image_stats["reasons"]["bad_dimensions"] += 1
            return None
        ratio = w / float(h or 1)
        min_ratio = float(getattr(config, "IMAGE_MIN_RATIO", 0.0))
        max_ratio = float(getattr(config, "IMAGE_MAX_RATIO", 10.0))
        if ratio < min_ratio or ratio > max_ratio:
            image_stats["reasons"]["bad_ratio"] += 1
            return None
        ihash = hashlib.sha256(data).hexdigest()
        cached = images_cache.get(ihash)
        if cached:
            return cached, ihash
        file_id = f"file_{ihash[:32]}"
        images_cache[ihash] = file_id
        if conn is not None:
            conn.execute(
                "INSERT OR REPLACE INTO images_cache(src_url, hash, width, height, tg_file_id) VALUES (?,?,?,?,?)",
                (image_url, ihash, w, h, file_id),
            )
            conn.commit()
        image_stats["with_image"] += 1
        return file_id, ihash
    except Exception as ex:  # pragma: no cover
        log.debug("ensure_tg_file_id failed for %s: %s", image_url, ex)
        return None

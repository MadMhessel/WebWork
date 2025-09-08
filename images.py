from __future__ import annotations
import hashlib
import logging
import os
import re
import json
from html import unescape
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
try:
    from . import config, db, http_client
except ImportError:  # pragma: no cover
    import config, db, http_client  # type: ignore

HTTP_SESSION = http_client.get_session()

log = logging.getLogger(__name__)

# simple in-memory cache: image_hash -> tg_file_id
images_cache: dict[str, str] = {}
image_stats = {"with_image": 0, "reasons": Counter()}


_JSON_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)


@dataclass
class ImageCandidate:
    url: str


def extract_candidates(item: dict) -> List[ImageCandidate]:
    """Extract potential image URLs from item dict.

    Combines direct ``image_url`` field, ``<img>`` tags and JSON‑LD blocks
    into a single list of unique, pre‑filtered candidates. This effectively
    merges levels A and B of the fallback funnel into one extractor function,
    simplifying subsequent selection logic.
    """
    content = item.get("content") or ""
    urls: List[str] = []

    # explicit field or RSS enclosure
    u0 = item.get("image_url")
    if u0:
        urls.append(u0)

    # inline images in article body
    urls.extend(re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', content, flags=re.I))

    # JSON-LD blocks often contain clean cover images
    for block in _JSON_LD_RE.findall(content):
        try:
            data = json.loads(unescape(block))
        except Exception:
            continue
        for url in _json_ld_image_urls(data):
            urls.append(url)

    seen: set[str] = set()
    out: List[ImageCandidate] = []
    for u in urls:
        if not u or u in seen:
            continue
        seen.add(u)
        if is_reasonable_image_url(u):
            out.append(ImageCandidate(url=u))
    return out


def _json_ld_image_urls(obj) -> List[str]:
    urls: List[str] = []
    if isinstance(obj, str):
        urls.append(obj)
    elif isinstance(obj, dict):
        img = obj.get("image") or obj.get("url") or obj.get("@id")
        if isinstance(img, (str, dict, list)):
            urls.extend(_json_ld_image_urls(img))
    elif isinstance(obj, list):
        for it in obj:
            urls.extend(_json_ld_image_urls(it))
    return urls


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


def select_image_with_fallback(item: dict) -> Optional[str]:
    """Try multiple strategies to obtain image URL for news item.

    Implements levels A and B of the fallback funnel and finally returns
    configured placeholder image (levels F–H) if nothing else matched.
    """
    cand = pick_best(extract_candidates(item))
    if cand:
        return cand.url

    # TODO: implement levels C–E (official channels, open licenses)

    fallback = getattr(config, "FALLBACK_IMAGE_URL", "")
    if fallback:
        return fallback
    return None


def resolve_image(item: dict, conn: Optional[sqlite3.Connection] = None) -> dict:
    """Resolve image URL and Telegram file id for ``item``.

    The function first tries to pick the best candidate from the article
    itself (levels A–B). If validation via ``ensure_tg_file_id`` fails, it
    retries with the configured fallback image to guarantee that at least some
    visual is attached to the post (SLA 100%).

    Returns a dict that may contain ``image_url``, ``tg_file_id`` and
    ``image_hash`` keys depending on which steps succeeded. ``image_url`` is
    always present when a fallback is configured.
    """

    best_url = select_image_with_fallback(item)
    fallback_url = getattr(config, "FALLBACK_IMAGE_URL", "")

    urls_to_try: List[str] = []
    if best_url:
        urls_to_try.append(best_url)
    if fallback_url and fallback_url not in urls_to_try:
        urls_to_try.append(fallback_url)

    result: dict = {}
    for url in urls_to_try:
        res = ensure_tg_file_id(url, conn)
        if res:
            fid, ihash = res
            result = {"image_url": url, "tg_file_id": fid, "image_hash": ihash}
            break

    if not result:
        if fallback_url:
            result = {"image_url": fallback_url}
        elif urls_to_try:
            result = {"image_url": urls_to_try[0]}
    return result


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

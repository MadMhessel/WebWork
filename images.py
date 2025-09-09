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
from urllib.parse import urlparse, urljoin

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


def _best_from_srcset(srcset: str) -> Optional[str]:
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
    urls.extend(_IMG_RE.findall(content))
    for srcset in _SRCSET_RE.findall(content):
        best = _best_from_srcset(srcset)
        if best:
            urls.append(best)

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
        if not u:
            continue
        if item.get("url"):
            u = urljoin(item["url"], u)
        if u in seen or _PLACEHOLDER_RE.search(u):
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
        img = (
            obj.get("image")
            or obj.get("thumbnailUrl")
            or obj.get("url")
            or obj.get("@id")
        )
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
    if _PLACEHOLDER_RE.search(low):
        return False
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


def _score_url(url: str) -> int:
    low = url.lower()
    if _PLACEHOLDER_RE.search(low):
        return -100
    score = 0
    if any(k in low for k in {"logo", "sprite", "icon"}):
        score -= 20
    m = re.search(r"(\d{2,4})x(\d{2,4})", low)
    if m:
        score += int(m.group(1)) + int(m.group(2))
    if "@2x" in low or "@3x" in low:
        score += 10
    return score


def pick_best(candidates: List[ImageCandidate]) -> Optional[ImageCandidate]:
    """Pick highest-scoring candidate respecting domain whitelist."""
    best = None
    best_score = -999
    for cand in candidates:
        if not _domain_allowed(cand.url):
            continue
        s = _score_url(cand.url)
        if s > best_score:
            best_score = s
            best = cand
    return best


def select_image_with_fallback(item: dict) -> Optional[str]:
    """Try multiple strategies to obtain image URL for news item.

    Implements levels A and B of the fallback funnel and finally returns
    configured placeholder image (levels F–H) if nothing else matched.
    """
    cands = extract_candidates(item)
    log.debug("extract_image_candidates n=%d top=%s", len(cands), [c.url for c in cands[:3]])
    cand = pick_best(cands)
    if cand:
        return cand.url

    # TODO: implement levels C–E (official channels, open licenses)

    fallback = getattr(config, "FALLBACK_IMAGE_URL", "")
    if fallback:
        log.info("select_image_with_fallback: using fallback %s", fallback)
        return fallback
    return None


def resolve_image(item: dict, conn: Optional[sqlite3.Connection] = None) -> dict:
    """Resolve best image URL for ``item`` and validate it.

    Returns a dict with ``image_url`` and optionally ``image_hash`` when the
    image passes validation via :func:`probe_image`.
    """

    url = select_image_with_fallback(item)
    if not url:
        return {}

    info = {"image_url": url}
    try:
        res = probe_image(url, referer=item.get("url"))
        if not res:
            fb = getattr(config, "FALLBACK_IMAGE_URL", "")
            if fb and fb != url:
                info["image_url"] = fb
                res = probe_image(fb, referer=item.get("url"))
        if res:
            ihash, w, h = res
            info["image_hash"] = ihash
            if conn is not None:
                conn.execute(
                    "INSERT OR REPLACE INTO images_cache(src_url, hash, width, height) VALUES (?,?,?,?)",
                    (info["image_url"], ihash, w, h),
                )
                conn.commit()
    except Exception:
        pass
    return info


def probe_image(image_url: str, referer: Optional[str] = None) -> Optional[tuple[str, int, int]]:
    """Validate image via HTTP and Pillow without uploading to Telegram."""
    if not image_url or not getattr(config, "ALLOW_IMAGES", True):
        return None

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "ru,en;q=0.8",
    }
    if referer:
        headers["Referer"] = referer

    session = HTTP_SESSION
    try:
        head = session.head(
            image_url,
            headers=headers,
            timeout=(config.HTTP_TIMEOUT_CONNECT, config.HTTP_TIMEOUT_READ),
            allow_redirects=True,
        )
        if head.status_code in {403, 405}:  # immediately fallback to GET
            head = None
        try:
            if head is not None:
                ctype = head.headers.get("Content-Type", "")
                if head.status_code != 200 or not ctype.startswith("image/"):
                    image_stats["reasons"]["invalid_content_type"] += 1
                    return None
                clen = int(head.headers.get("Content-Length", "0") or "0")
                if clen < int(getattr(config, "MIN_IMAGE_BYTES", 0)):
                    image_stats["reasons"]["too_small"] += 1
                    return None
        finally:
            if head is not None and hasattr(head, "close"):
                head.close()
        r = session.get(
            image_url,
            headers=headers,
            timeout=(config.HTTP_TIMEOUT_CONNECT, config.HTTP_TIMEOUT_READ),
            allow_redirects=True,
        )
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
        image_stats["with_image"] += 1
        return ihash, w, h
    except Exception as ex:  # pragma: no cover
        log.debug("probe_image failed for %s: %s", image_url, ex)
        return None


def ensure_tg_file_id(
    image_url: str, conn: Optional[sqlite3.Connection] = None
) -> Optional[tuple[Optional[str], str]]:
    """Fetch cached Telegram ``file_id`` for ``image_url`` if available.

    This function no longer generates pseudo identifiers. When called, it
    returns ``(tg_file_id, image_hash)`` if present in cache or ``(None, hash)``
    after probing the image.
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
            "SELECT tg_file_id, hash, width, height FROM images_cache WHERE src_url = ?",
            (image_url,),
        )
        row = cur.fetchone()
        if row:
            return row["tg_file_id"], row["hash"]

    res = probe_image(image_url)
    if res and conn is not None:
        ihash, w, h = res
        conn.execute(
            "INSERT OR REPLACE INTO images_cache(src_url, hash, width, height) VALUES (?,?,?,?)",
            (image_url, ihash, w, h),
        )
        conn.commit()
        return None, ihash
    return None

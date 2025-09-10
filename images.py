from __future__ import annotations
import hashlib
import io
import json
import logging
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

try:
    from . import config, db, context_images, net  # type: ignore
except Exception:  # pragma: no cover
    import config  # type: ignore
    import db  # type: ignore
    import context_images  # type: ignore
    import net  # type: ignore

try:
    from PIL import Image  # type: ignore

    PIL_OK = True
except Exception:  # pragma: no cover
    Image = None  # type: ignore
    PIL_OK = False

try:  # pragma: no cover - optional dependency
    import imagehash  # type: ignore

    IMAGEHASH_OK = True
except Exception:  # pragma: no cover
    imagehash = None  # type: ignore
    IMAGEHASH_OK = False

logger = logging.getLogger(__name__)

# -------------------- Константы/настройки (можно переопределить из config) --------------------

USER_AGENT = "tg_newsbot/1.0 (+https://example.com)"
IMAGE_TIMEOUT = getattr(config, "IMAGE_TIMEOUT", 15)
MIN_BYTES = int(getattr(config, "MIN_IMAGE_BYTES", 4096))
MAX_BYTES = 7_500_000
MIN_WIDTH = MIN_HEIGHT = int(getattr(config, "IMAGE_MIN_EDGE", 220))
MIN_AREA = int(getattr(config, "IMAGE_MIN_AREA", 45000))
MIN_RATIO = float(getattr(config, "IMAGE_MIN_RATIO", 0.5))
MAX_RATIO = float(getattr(config, "IMAGE_MAX_RATIO", 3.0))
ALLOWED_DOMAINS = {
    d.lower() for d in getattr(config, "IMAGE_ALLOWED_DOMAINS", set()) if d
}
ALLOWED_EXT = {
    e.lower()
    for e in getattr(
        config, "IMAGE_ALLOWED_EXT", {".jpg", ".jpeg", ".png", ".webp", ".avif"}
    )
}
FALLBACK_IMAGE_URL = getattr(config, "FALLBACK_IMAGE_URL", "")
ATTACH_IMAGES = bool(getattr(config, "ATTACH_IMAGES", True))
ALLOW_PLACEHOLDER = bool(getattr(config, "ALLOW_PLACEHOLDER", False))

IMAGES_CACHE_DIR = Path(getattr(config, "IMAGES_CACHE_DIR", "./cache/images"))
MAX_SIDE = 1600

_PHASH_CACHE: Dict[str, Path] = {}

# Фильтры «мусора» и плейсхолдеров
PLACEHOLDER_RE = re.compile(
    r"(placeholder|plug|zaglush|no-?image|spacer|sprite|counter|pixel|metrika|yandex|stats?)",
    re.I,
)

# -------------------- Публичные структуры/метрики --------------------

image_stats: Dict[str, int] = {
    "checked": 0,
    "with_image": 0,
    "no_candidate": 0,
    "filtered_out": 0,
    "too_small": 0,
    "bad_bytes": 0,
    "download_fail": 0,
    "converted_webp": 0,
}


@dataclass
class ImageCandidate:
    url: str
    source: str = ""  # enclosure|og|twitter|jsonld|content|srcset


# -------------------- Вспомогательные функции парсинга HTML --------------------

_META_OG = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', re.I
)
_META_OG_SEC = re.compile(
    r'<meta[^>]+property=["\']og:image:secure_url["\'][^>]+content=["\']([^"\']+)["\']',
    re.I,
)
_META_TW = re.compile(
    r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']', re.I
)
_JSON_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S
)
_IMG_SRC_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.I)
_IMG_DATASRC_RE = re.compile(r'<img[^>]+data-src=["\']([^"\']+)["\']', re.I)
_IMG_SRCSET_RE = re.compile(r'<img[^>]+srcset=["\']([^"\']+)["\']', re.I)


def _abs(base: Optional[str], url: str) -> str:
    try:
        return urljoin(base or "", url)
    except Exception:
        return url


def _parse_srcset(srcset: str) -> List[str]:
    out: List[str] = []
    for part in srcset.split(","):
        part = part.strip()
        if not part:
            continue
        url = part.split()[0]
        if url:
            out.append(url)
    return out


def _json_ld_images(html: str) -> List[str]:
    urls: List[str] = []
    for m in _JSON_LD_RE.finditer(html):
        try:
            data = json.loads(unescape(m.group(1)))
        except Exception:
            continue
        for key in ("image", "thumbnailUrl", "thumbnail"):
            if key in data:
                v = data[key]
                if isinstance(v, str):
                    urls.append(v)
                elif isinstance(v, list):
                    urls.extend([str(x) for x in v if x])
    return urls


# -------------------- Кандидаты и выбор --------------------


def extract_candidates(item: Dict) -> List[ImageCandidate]:
    """
    Собирает кандидатные URL картинок в порядке приоритета.
    item: ожидаются поля item["url"], item["content"], item["enclosure"], item["image_url"] (если парсер уже нашёл).
    """
    base = item.get("url") or ""
    html = item.get("content") or ""
    out: List[ImageCandidate] = []

    # 0) «готовые» поля, если есть
    if item.get("image_url"):
        out.append(ImageCandidate(_abs(base, item["image_url"]), "content"))
    if item.get("enclosure"):
        out.append(ImageCandidate(_abs(base, item["enclosure"]), "enclosure"))

    # 1) мета-теги
    for rx, src in ((_META_OG, "og"), (_META_OG_SEC, "og"), (_META_TW, "twitter")):
        for m in rx.finditer(html):
            out.append(ImageCandidate(_abs(base, unescape(m.group(1))), src))

    # 2) JSON-LD
    for u in _json_ld_images(html):
        out.append(ImageCandidate(_abs(base, u), "jsonld"))

    # 3) <img src|data-src|srcset>
    for m in _IMG_SRC_RE.finditer(html):
        out.append(ImageCandidate(_abs(base, unescape(m.group(1))), "content"))
    for m in _IMG_DATASRC_RE.finditer(html):
        out.append(ImageCandidate(_abs(base, unescape(m.group(1))), "content"))
    for m in _IMG_SRCSET_RE.finditer(html):
        for u in _parse_srcset(unescape(m.group(1))):
            out.append(ImageCandidate(_abs(base, u), "srcset"))

    # фильтры/нормализация
    final: List[ImageCandidate] = []
    seen: set = set()
    for c in out:
        u = (c.url or "").strip()
        if not u:
            continue
        if u in seen:
            continue
        low = u.lower()
        if low.startswith("data:"):
            continue
        if low.endswith(".svg"):
            continue
        if PLACEHOLDER_RE.search(low):
            continue
        host = (urlparse(u).hostname or "").lower()
        if ALLOWED_DOMAINS and host not in ALLOWED_DOMAINS:
            continue
        ext = os.path.splitext(urlparse(u).path)[1].lower()
        if ALLOWED_EXT and ext and ext not in ALLOWED_EXT:
            continue
        seen.add(u)
        final.append(ImageCandidate(u, c.source))

    return final


def select_image(item: Dict, cfg=config) -> Optional[str]:
    """Return best image URL for item or FALLBACK."""
    cands = extract_candidates(item)
    best_url: Optional[str] = None
    best_area = 0
    for cand in cands:
        if not net.is_downloadable_image_url(cand.url):
            continue
        info = probe_image(cand.url, referer=item.get("url"))
        if not info:
            continue
        _hash, w, h = info
        area = w * h
        ratio = w / h if h else 0
        if w < MIN_WIDTH or h < MIN_HEIGHT or area < MIN_AREA:
            continue
        if ratio < MIN_RATIO or ratio > MAX_RATIO:
            continue
        if area > best_area:
            best_area = area
            best_url = cand.url
    if best_url:
        return best_url
    if ATTACH_IMAGES and FALLBACK_IMAGE_URL and ALLOW_PLACEHOLDER:
        return FALLBACK_IMAGE_URL
    return None


# -------------------- Работа с БД кэша --------------------


def _ensure_cache_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS images_cache (
            src_url   TEXT PRIMARY KEY,
            hash      TEXT,
            width     INTEGER,
            height    INTEGER,
            tg_file_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_images_cache_hash ON images_cache(hash)"
    )
    conn.commit()


def ensure_tg_file_id(
    image_url: str, conn: Optional[sqlite3.Connection] = None
) -> Tuple[Optional[str], Optional[str]]:
    """
    Возвращает (tg_file_id, hash). Если записи нет — вычисляет hash/размеры и кладёт в кэш (tg_file_id остаётся None).
    """
    if not image_url:
        return None, None
    if conn is not None:
        _ensure_cache_schema(conn)
        row = conn.execute(
            "SELECT tg_file_id, hash FROM images_cache WHERE src_url = ?", (image_url,)
        ).fetchone()
        if row:
            return row["tg_file_id"], row["hash"]

    res = probe_image(image_url)
    if res:
        ihash, w, h = res
        if conn is not None:
            conn.execute(
                "INSERT OR IGNORE INTO images_cache(src_url, hash, width, height) VALUES (?,?,?,?)",
                (image_url, ihash, w, h),
            )
            conn.commit()
        return None, ihash
    return None, None


# -------------------- Скачивание/валидация --------------------


def _headers(referer: Optional[str] = None) -> Dict[str, str]:
    h = {"User-Agent": USER_AGENT, "Accept": "image/*,*/*;q=0.8"}
    if referer:
        h["Referer"] = referer
    return h


def _probe_bytes(raw: bytes) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    mime = "application/octet-stream"
    w = h = None
    # простейшее определение по сигнатурам + Pillow
    if raw.startswith(b"\xff\xd8"):
        mime = "image/jpeg"
    elif raw.startswith(b"\x89PNG"):
        mime = "image/png"
    elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        mime = "image/webp"
    if PIL_OK:
        try:
            with Image.open(io.BytesIO(raw)) as im:
                w, h = im.size
                fmt = (im.format or "").lower()
                if fmt == "jpeg" or fmt == "jpg":
                    mime = "image/jpeg"
                elif fmt == "png":
                    mime = "image/png"
                elif fmt == "webp":
                    mime = "image/webp"
        except Exception:
            pass
    return w, h, mime


def _to_jpeg(raw: bytes) -> Tuple[bytes, int, int]:
    if not PIL_OK:
        raise RuntimeError("Pillow not installed, cannot convert to JPEG")
    with Image.open(io.BytesIO(raw)) as im:
        if im.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=88, optimize=True)
        out = buf.getvalue()
        return out, im.size[0], im.size[1]


def probe_image(
    url: str, referer: Optional[str] = None
) -> Optional[Tuple[str, int, int]]:
    """
    HEAD -> GET, проверяем размер, минимум байт, пробуем распарсить размер.
    Возвращает (sha1-hex[:16], width, height) или None.
    """
    if not net.is_downloadable_image_url(url):
        return None
    try:
        raw = net.get_bytes(url, headers=_headers(referer), timeout=IMAGE_TIMEOUT)
    except Exception:
        image_stats["download_fail"] += 1
        return None
    if len(raw) > MAX_BYTES:
        image_stats["bad_bytes"] += 1
        return None

    if len(raw) < MIN_BYTES:
        image_stats["bad_bytes"] += 1
        return None

    w, h, mime = _probe_bytes(raw)
    if not w or not h:
        image_stats["too_small"] += 1
        return None
    area = w * h
    ratio = w / h if h else 0
    if w < MIN_WIDTH or h < MIN_HEIGHT or area < MIN_AREA:
        image_stats["too_small"] += 1
        return None
    if ratio < MIN_RATIO or ratio > MAX_RATIO:
        image_stats["filtered_out"] += 1
        return None
    if mime == "image/webp":
        try:
            raw2, w2, h2 = _to_jpeg(raw)
            raw = raw2
            w, h = w2, h2
            image_stats["converted_webp"] += 1
        except Exception:
            # если Pillow нет — оставим webp, дальше отсеется по mime/размеру
            pass

    if not w or not h or w < MIN_WIDTH or h < MIN_HEIGHT:
        image_stats["too_small"] += 1
        return None

    # сам hash считаем от пикс-данных, чтобы устойчиво матчить
    ihash = hashlib.sha1(raw).hexdigest()[:16]
    return ihash, int(w), int(h)


def download_image(
    url: str, referer: Optional[str] = None
) -> Optional[Tuple[bytes, str]]:
    """
    Скачивает изображение (с конвертацией webp->jpeg при наличии Pillow).
    Возвращает (bytes, mime) или None.
    """
    if not net.is_downloadable_image_url(url):
        return None
    try:
        raw = net.get_bytes(url, headers=_headers(referer), timeout=IMAGE_TIMEOUT)
    except Exception:
        image_stats["download_fail"] += 1
        return None

    if len(raw) < MIN_BYTES or len(raw) > MAX_BYTES:
        image_stats["bad_bytes"] += 1
        return None

    w, h, mime = _probe_bytes(raw)
    if mime == "image/webp":
        try:
            raw, w, h = _to_jpeg(raw)
            mime = "image/jpeg"
            image_stats["converted_webp"] += 1
        except Exception:
            pass

    if not w or not h:
        image_stats["too_small"] += 1
        return None
    area = w * h
    ratio = w / h if h else 0
    if w < MIN_WIDTH or h < MIN_HEIGHT or area < MIN_AREA:
        image_stats["too_small"] += 1
        return None
    if ratio < MIN_RATIO or ratio > MAX_RATIO:
        image_stats["filtered_out"] += 1
        return None

    return raw, (mime or "image/jpeg")


def _save_and_hash(raw: bytes, url: str) -> Dict[str, object]:
    """Save image to cache and compute perceptual hash."""

    ts = datetime.utcnow()
    subdir = IMAGES_CACHE_DIR / ts.strftime("%y/%m")
    subdir.mkdir(parents=True, exist_ok=True)
    file_path = subdir / (hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ".jpg")
    if IMAGEHASH_OK and PIL_OK:
        img = Image.open(io.BytesIO(raw))
        if img.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        img.save(file_path, format="JPEG", quality=85)
        phash = str(imagehash.phash(img))
        width, height = img.size
    else:  # pragma: no cover - imagehash not available
        with open(file_path, "wb") as f:
            f.write(raw)
        phash = hashlib.sha1(raw).hexdigest()
        width = height = 0

    if phash in _PHASH_CACHE:
        file_path = _PHASH_CACHE[phash]
    else:
        _PHASH_CACHE[phash] = file_path

    return {
        "local_path": str(file_path),
        "phash": phash,
        "width": width,
        "height": height,
    }


def pick_and_download(urls: List[str]) -> Optional[Dict[str, object]]:
    """Download first valid image from URLs.

    The image is validated, converted to JPEG if necessary and cached on disk.
    A dictionary describing the image (path, hash, dimensions) is returned.
    """

    for u in urls:
        payload = download_image(u)
        if not payload:
            continue
        raw, _ = payload
        info = _save_and_hash(raw, u)
        return info
    return None


# -------------------- Главная точка для пайплайна --------------------


def resolve_image(item: Dict, conn: Optional[sqlite3.Connection] = None) -> Dict:
    """Resolve and download image for a news item.

    Returns dictionary ready for Telegram ``sendPhoto`` or empty dict if none
    found.  Tries context providers according to configuration and always
    returns local bytes or a cached ``tg_file_id``.
    """

    image_stats["checked"] += 1

    use_context = getattr(config, "CONTEXT_IMAGE_ENABLED", True)
    prefer_context = getattr(config, "CONTEXT_IMAGE_PREFERRED", False)

    # 1) Context image first
    if use_context and prefer_context:
        ctx = context_images.fetch_context_image(item, config)
        if ctx:
            if conn:
                fid = db.get_cached_file_id(conn, ctx["image_url"])
                if fid:
                    ctx["tg_file_id"] = fid
                    ctx.pop("bytes", None)
            image_stats["with_image"] += 1
            return ctx

    # 2) Image from original site
    url = select_image(item)
    if url:
        if url == FALLBACK_IMAGE_URL:
            return {"image_url": url}
        fid = None
        if conn:
            try:
                fid = db.get_cached_file_id(conn, url)
            except Exception:
                fid = None
        if fid:
            image_stats["with_image"] += 1
            return {"image_url": url, "tg_file_id": fid}
        payload = download_image(url, referer=item.get("url"))
        if payload:
            raw, mime = payload
            w, h, _ = _probe_bytes(raw)
            ihash = hashlib.sha1(raw).hexdigest()[:16]
            image_stats["with_image"] += 1
            return {
                "image_url": url,
                "bytes": raw,
                "mime": mime,
                "image_hash": ihash,
                "width": int(w or 0),
                "height": int(h or 0),
                "tg_file_id": None,
            }

    # 3) Context fallback
    if use_context:
        ctx = context_images.fetch_context_image(item, config)
        if ctx:
            if conn:
                fid = db.get_cached_file_id(conn, ctx["image_url"])
                if fid:
                    ctx["tg_file_id"] = fid
                    ctx.pop("bytes", None)
            image_stats["with_image"] += 1
            return ctx

    # 4) Placeholder or empty
    if ATTACH_IMAGES and FALLBACK_IMAGE_URL and ALLOW_PLACEHOLDER:
        return {"image_url": FALLBACK_IMAGE_URL}
    image_stats["no_candidate"] += 1
    return {}

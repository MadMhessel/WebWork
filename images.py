from __future__ import annotations
import base64
import hashlib
import io
import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from html import unescape
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests

try:
    from PIL import Image  # type: ignore
    PIL_OK = True
except Exception:  # pragma: no cover
    Image = None  # type: ignore
    PIL_OK = False

logger = logging.getLogger(__name__)

# -------------------- Константы/настройки (можно переопределить из config) --------------------

USER_AGENT = "tg_newsbot/1.0 (+https://example.com)"
TIMEOUT_HEAD = 5.0
TIMEOUT_GET = 12.0
MIN_BYTES = 10_240          # >= 10 КБ
MAX_BYTES = 7_500_000       # < 7.5 МБ
MIN_WIDTH, MIN_HEIGHT = 320, 200  # Плейсхолдер не используем — при отсутствии картинки отправляем пост без фото
ALLOW_PLACEHOLDER = False

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

_META_OG = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', re.I)
_META_OG_SEC = re.compile(r'<meta[^>]+property=["\']og:image:secure_url["\'][^>]+content=["\']([^"\']+)["\']', re.I)
_META_TW = re.compile(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']', re.I)
_JSON_LD_RE = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)
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
        seen.add(u)
        final.append(ImageCandidate(u, c.source))

    return final

def select_image(item: Dict) -> Optional[str]:
    """
    Возвращает лучший URL изображения (без скачивания), либо None.
    Приоритет: enclosure > og > twitter > jsonld > content/srcset.
    """
    cands = extract_candidates(item)
    if not cands:
        return None
    priority = {"enclosure": 0, "og": 1, "twitter": 2, "jsonld": 3, "content": 4, "srcset": 5}
    cands.sort(key=lambda c: (priority.get(c.source, 99), c.url))
    return cands[0].url if cands else None

# -------------------- Работа с БД кэша --------------------

def _ensure_cache_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS images_cache (
            src_url   TEXT PRIMARY KEY,
            hash      TEXT,
            width     INTEGER,
            height    INTEGER,
            tg_file_id TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_images_cache_hash ON images_cache(hash)")
    conn.commit()

def ensure_tg_file_id(image_url: str, conn: Optional[sqlite3.Connection] = None) -> Tuple[Optional[str], Optional[str]]:
    """
    Возвращает (tg_file_id, hash). Если записи нет — вычисляет hash/размеры и кладёт в кэш (tg_file_id остаётся None).
    """
    if not image_url:
        return None, None
    if conn is not None:
        _ensure_cache_schema(conn)
        row = conn.execute("SELECT tg_file_id, hash FROM images_cache WHERE src_url = ?", (image_url,)).fetchone()
        if row:
            return row["tg_file_id"], row["hash"]

    res = probe_image(image_url)
    if res:
        ihash, w, h = res
        if conn is not None:
            conn.execute(
                "INSERT OR REPLACE INTO images_cache(src_url, hash, width, height, tg_file_id) VALUES (?,?,?,?,COALESCE((SELECT tg_file_id FROM images_cache WHERE src_url=?), NULL))",
                (image_url, ihash, w, h, image_url),
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
    if raw.startswith(b"\xFF\xD8"):
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

def probe_image(url: str, referer: Optional[str] = None) -> Optional[Tuple[str, int, int]]:
    """
    HEAD -> GET, проверяем размер, минимум байт, пробуем распарсить размер.
    Возвращает (sha1-hex[:16], width, height) или None.
    """
    try:
        r = requests.head(url, allow_redirects=True, timeout=TIMEOUT_HEAD, headers=_headers(referer))
        if r.status_code >= 400:
            image_stats["download_fail"] += 1
            return None
    except Exception:
        # многие сайты режут HEAD — идём дальше
        pass

    try:
        g = requests.get(url, stream=True, timeout=TIMEOUT_GET, headers=_headers(referer))
        g.raise_for_status()
        buf = io.BytesIO()
        total = 0
        for chunk in g.iter_content(64 * 1024):
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_BYTES:
                image_stats["bad_bytes"] += 1
                return None
            buf.write(chunk)
        raw = buf.getvalue()
    except Exception:
        image_stats["download_fail"] += 1
        return None

    if len(raw) < MIN_BYTES:
        image_stats["bad_bytes"] += 1
        return None

    w, h, mime = _probe_bytes(raw)
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

def download_image(url: str, referer: Optional[str] = None) -> Optional[Tuple[bytes, str]]:
    """
    Скачивает изображение (с конвертацией webp->jpeg при наличии Pillow).
    Возвращает (bytes, mime) или None.
    """
    try:
        g = requests.get(url, stream=True, timeout=TIMEOUT_GET, headers=_headers(referer))
        g.raise_for_status()
        raw = g.content
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

    if not w or not h or w < MIN_WIDTH or h < MIN_HEIGHT:
        image_stats["too_small"] += 1
        return None

    return raw, (mime or "image/jpeg")

# -------------------- Главная точка для пайплайна --------------------

def resolve_image(item: Dict, conn: Optional[sqlite3.Connection] = None) -> Dict:
    """
    Пытается найти и подготовить картинку для поста.
    Возвращает dict либо пустой {}:
      {
        "url": "...",
        "bytes": b"...",      # готово для sendPhoto
        "mime": "image/jpeg",
        "hash": "abcd1234ef...",
        "width": 1200,
        "height": 630,
      }
    """
    image_stats["checked"] += 1

    url = select_image(item)
    if not url:
        image_stats["no_candidate"] += 1
        return {}

    # кешируем hash/размеры (и, если будет, tg_file_id)
    tg_file_id, ihash = ensure_tg_file_id(url, conn)

    # скачиваем для отправки
    payload = download_image(url, referer=item.get("url"))
    if not payload:
        image_stats["download_fail"] += 1
        return {}

    raw, mime = payload
    w, h, _ = _probe_bytes(raw)

    image_stats["with_image"] += 1
    return {
        "url": url,
        "bytes": raw,
        "mime": mime,
        "hash": ihash or hashlib.sha1(raw).hexdigest()[:16],
        "width": int(w or 0),
        "height": int(h or 0),
        "tg_file_id": tg_file_id,  # может быть None — это нормально
    }

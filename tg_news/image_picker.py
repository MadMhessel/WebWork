import io
import imghdr
import logging
import mimetypes
import re
from dataclasses import dataclass
from html import unescape
from typing import Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests

try:
    from PIL import Image  # type: ignore
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

logger = logging.getLogger(__name__)

# --- Публичный интерфейс -----------------------------------------------------
@dataclass
class ImageData:
    source: str            # 'enclosure' | 'og' | 'twitter' | 'content'
    url: str               # исходный URL (может быть пуст, если локальный байтовый контент)
    content: bytes         # готовый к отправке JPEG/PNG
    width: int
    height: int
    mime: str              # 'image/jpeg' | 'image/png'
    note: str = ""         # причина выбора/конвертации

def pick_image_for_post(
    *,
    page_url: str,
    html: Optional[str],
    enclosure_url: Optional[str],
    config: dict,
) -> Optional[ImageData]:
    """
    Главная точка входа:
    - собирает кандидатов (enclosure, <img> из контента, og:image, twitter:image)
    - валидирует и скачивает
    - при необходимости конвертирует (webp/svg -> jpeg)
    - фильтрует по размеру и весу
    - возвращает лучший ImageData или None
    """
    if not config.get("images", {}).get("enabled", True):
        logger.info("image_picker: disabled by config")
        return None

    prefer: List[str] = config["images"].get("prefer", ["enclosure", "content", "og", "twitter"])
    min_w = int(config["images"].get("min_width", 320))
    min_h = int(config["images"].get("min_height", 200))
    min_b = int(config["images"].get("min_bytes", 10_240))
    max_b = int(config["images"].get("max_bytes", 7_500_000))
    timeout_s = float(config["images"].get("timeout_s", 8.0))
    ua = str(config["images"].get("user_agent", "tg_newsbot/1.0"))

    # 1) собрать кандидатов
    cands: List[Tuple[str, str]] = []  # (source, url)
    found = _extract_candidates(page_url=page_url, html=html, enclosure_url=enclosure_url)
    # упорядочим по предпочтениям
    for key in prefer:
        for src, url in found:
            if src == key:
                cands.append((src, url))
    # добавим всё остальное, что не вошло (на всякий случай)
    for src, url in found:
        if (src, url) not in cands:
            cands.append((src, url))

    if not cands:
        logger.info("image_picker: no candidates for %s", page_url)
        return None

    # 2) перебрать кандидатов, скачать и провалидировать
    for src, url in cands:
        try:
            item = _download_and_validate(
                url=url,
                timeout_s=timeout_s,
                ua=ua,
                min_w=min_w,
                min_h=min_h,
                min_b=min_b,
                max_b=max_b,
            )
            if item:
                item.source = src
                logger.info("image_picker: selected %s (%dx%d, %s) from %s", item.mime, item.width, item.height, item.url, src)
                return item
        except Exception as e:
            logger.warning("image_picker: candidate failed (%s): %s", url, e)

    # 3) если allow_placeholder=true — в крайнем случае вернём плейсхолдер (мы отключаем по умолчанию)
    allow_placeholder = bool(config["images"].get("allow_placeholder", False))
    if allow_placeholder:
        ph_path = str(config["images"].get("placeholder_path", "./assets/placeholder.png"))
        try:
            with open(ph_path, "rb") as f:
                content = f.read()
            # попытка оценить размер
            width, height, mime = _probe_image(content)
            if width and height and mime:
                return ImageData(
                    source="placeholder",
                    url="",
                    content=content,
                    width=width,
                    height=height,
                    mime=mime,
                    note="placeholder",
                )
        except Exception as e:
            logger.warning("image_picker: placeholder failed: %s", e)

    return None

# --- Внутренности ------------------------------------------------------------
IMG_TAG_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
META_OG_RE = re.compile(r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']', re.IGNORECASE)
META_TW_RE = re.compile(r'<meta\s+name=["\']twitter:image["\']\s+content=["\']([^"\']+)["\']', re.IGNORECASE)

def _extract_candidates(*, page_url: str, html: Optional[str], enclosure_url: Optional[str]) -> List[Tuple[str, str]]:
    base = page_url or ""
    out: List[Tuple[str, str]] = []

    # 0) enclosure из RSS/ATOM
    if enclosure_url:
        out.append(("enclosure", _abs_url(base, enclosure_url)))

    if html:
        doc = html
        # 1) <img> в контенте
        for m in IMG_TAG_RE.finditer(doc):
            u = unescape(m.group(1)).strip()
            if u:
                out.append(("content", _abs_url(base, u)))
        # 2) og:image
        for m in META_OG_RE.finditer(doc):
            u = unescape(m.group(1)).strip()
            if u:
                out.append(("og", _abs_url(base, u)))
        # 3) twitter:image
        for m in META_TW_RE.finditer(doc):
            u = unescape(m.group(1)).strip()
            if u:
                out.append(("twitter", _abs_url(base, u)))

    # убрать явные мусорные/пустые
    out = [(s,u) for (s,u) in out if _seems_image_url(u)]
    # дедуп по URL (сохраняем порядок)
    seen = set()
    uniq: List[Tuple[str, str]] = []
    for s,u in out:
        if u not in seen:
            seen.add(u)
            uniq.append((s,u))
    return uniq

def _abs_url(base: str, u: str) -> str:
    try:
        return urljoin(base, u)
    except Exception:
        return u

def _seems_image_url(u: str) -> bool:
    if not u or len(u) < 5:
        return False
    # отбрасываем data: и svg (часто не поддерживается)
    if u.startswith("data:"):
        return False
    low = u.lower()
    if ".svg" in low:
        return False
    return True

def _download_and_validate(
    *,
    url: str,
    timeout_s: float,
    ua: str,
    min_w: int,
    min_h: int,
    min_b: int,
    max_b: int,
) -> Optional[ImageData]:
    headers = {"User-Agent": ua, "Accept": "image/*,*/*;q=0.8"}
    # иногда HEAD у многих сайтов режется; идём сразу GET c stream
    resp = requests.get(url, headers=headers, timeout=timeout_s, stream=True)
    resp.raise_for_status()

    # ограничиваем размер в рантайме
    content = io.BytesIO()
    total = 0
    chunk_sz = 64 * 1024
    for chunk in resp.iter_content(chunk_size=chunk_sz):
        if not chunk:
            break
        total += len(chunk)
        if total > max_b:
            raise ValueError(f"image too large: {total} > {max_b}")
        content.write(chunk)
    raw = content.getvalue()

    if len(raw) < min_b:
        raise ValueError(f"image too small by bytes: {len(raw)} < {min_b}")

    width, height, mime = _probe_image(raw)

    # если формат неподдерживаемый — конвертируем в JPEG (нужно Pillow)
    if mime not in ("image/jpeg", "image/png"):
        if not PIL_AVAILABLE:
            raise ValueError(f"unsupported mime {mime} and Pillow not available")
        raw, mime, width, height, note = _convert_to_jpeg(raw)
        logger.info("image_picker: converted to jpeg (%s)", note)

    if width is None or height is None:
        raise ValueError("cannot detect dimensions")

    if width < min_w or height < min_h:
        raise ValueError(f"image too small: {width}x{height} < {min_w}x{min_h}")

    return ImageData(
        source="",
        url=url,
        content=raw,
        width=width,
        height=height,
        mime=mime,
        note="ok",
    )

def _probe_image(raw: bytes) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    mime = _guess_mime(raw)
    w = h = None
    if PIL_AVAILABLE:
        try:
            with Image.open(io.BytesIO(raw)) as im:
                w, h = im.size
                # уточняем mime
                fmt = (im.format or "").lower()
                if fmt in ("jpeg", "jpg"):
                    mime = "image/jpeg"
                elif fmt == "png":
                    mime = "image/png"
                elif fmt == "webp":
                    mime = "image/webp"
        except Exception:
            pass
    return w, h, mime

def _guess_mime(raw: bytes) -> str:
    # imghdr иногда врёт, но лучше, чем ничего
    kind = imghdr.what(None, h=raw)
    if kind == "jpeg":
        return "image/jpeg"
    if kind == "png":
        return "image/png"
    if kind == "gif":
        return "image/gif"
    if kind == "webp":
        return "image/webp"
    return "application/octet-stream"

def _convert_to_jpeg(raw: bytes) -> Tuple[bytes, str, int, int, str]:
    """
    Возвращает (bytes, mime, width, height, note)
    """
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow is required for conversion")
    with Image.open(io.BytesIO(raw)) as im:
        # SVG тут не откроется — мы svg заранее отбрасываем
        if im.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
            note = "alpha->white"
        else:
            im = im.convert("RGB")
            note = "rgb"
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=88, optimize=True)
        out = buf.getvalue()
        w, h = im.size
        return out, "image/jpeg", w, h, note

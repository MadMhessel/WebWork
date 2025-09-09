"""Image extraction, processing and Telegram upload helpers."""

import io
import os
import re
import hashlib
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup  # type: ignore
from PIL import Image, ImageOps  # type: ignore

try:  # pragma: no cover
    from . import images, http_client, config  # type: ignore
except Exception:  # pragma: no cover
    import images  # type: ignore
    import http_client  # type: ignore
    import config  # type: ignore


MIN_WIDTH = 600
MIN_HEIGHT = 400
MAX_DIM = 1600
JPEG_QUALITY = 85

TELEGRAM_API_URL = "https://api.telegram.org"

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/avif",
}
POSSIBLE_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")


logger = logging.getLogger(__name__)

_session = http_client.get_session()
_TIMEOUT = (config.HTTP_TIMEOUT_CONNECT, config.HTTP_TIMEOUT_READ)


@dataclass
class ImageCandidate:
    url: str
    width_hint: Optional[int] = None
    height_hint: Optional[int] = None
    score: float = 0.0


# --- Утилиты MarkdownV2 (экранирование подписи для Telegram) ---

_MD_V2_PATTERN = re.compile(r"([_*[]()~`>#+-=|{}.!])")

def escape_md_v2(text: str) -> str:
    return _MD_V2_PATTERN.sub(r"\\\1", text)

def clamp_caption(text: str, limit: int = 1024) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    # Обрезаем аккуратно по словам
    cut = text[: limit - 1]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut + "…"


# --- Извлечение HTML и кандидатов ---
def fetch_html(url: str) -> str:
    resp = _session.get(url, timeout=_TIMEOUT)
    ct = resp.headers.get("Content-Type", "")
    if "text/html" not in ct and "application/xhtml" not in ct and "<html" not in resp.text.lower():
        raise ValueError(f"Not an HTML page: {ct}")
    return resp.text

def parse_int(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    try:
        return int(re.sub(r"[^\d]", "", s))
    except Exception:
        return None

def extract_image_candidates(page_html: str, base_url: str) -> List[ImageCandidate]:
    soup = BeautifulSoup(page_html, "lxml")
    candidates: List[ImageCandidate] = []

    # 1) RSS/HTML enclosure-like <link rel="image_src"> (редко)
    for tag in soup.select('link[rel="image_src"]'):
        href = tag.get("href")
        if href:
            candidates.append(ImageCandidate(url=urljoin(base_url, href), score=0.8))

    # 2) OpenGraph/Twitter
    og = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
    tw = soup.find("meta", attrs={"name": "twitter:image"}) or soup.find("meta", property="twitter:image")
    for meta in [og, tw]:
        if meta and meta.get("content"):
            candidates.append(ImageCandidate(url=urljoin(base_url, meta["content"]), score=1.0))

    # 3) schema.org ImageObject
    for tag in soup.select('[itemprop="image"], meta[itemprop="image"]'):
        content = tag.get("content") or tag.get("src")
        if content:
            candidates.append(ImageCandidate(url=urljoin(base_url, content), score=0.9))

    # 4) Прямые <img>
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        if not src:
            continue
        w = parse_int(img.get("width"))
        h = parse_int(img.get("height"))
        score = 0.5
        # Повышаем вес за крупные подсказки размеров
        if (w or 0) >= 800 or (h or 0) >= 600:
            score += 0.2
        # Понижаем за маленькие превью
        if (w and w < 200) or (h and h < 200):
            score -= 0.3
        # Понижаем за sprite/ico/logo
        low_src = src.lower()
        if any(tok in low_src for tok in ["sprite", "icon", "favicon", "logo", "placeholder"]):
            score -= 0.4
        candidates.append(ImageCandidate(url=urljoin(base_url, src), width_hint=w, height_hint=h, score=score))

    # Убираем явный мусор по расширению/схеме
    cleaned: List[ImageCandidate] = []
    seen = set()
    for c in candidates:
        u = c.url
        if u.startswith("data:") or u.startswith("blob:"):
            continue
        if not urlparse(u).scheme in ("http", "https"):
            continue
        if not any(u.lower().split("?")[0].endswith(ext) for ext in POSSIBLE_IMAGE_EXT):
            # Разрешаем и без расширения, вдруг CDN
            pass
        key = u.split("#")[0]
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(c)

    return cleaned

def score_candidate_by_head(url: str, base_score: float) -> float:
    try:
        resp = _session.head(url, timeout=_TIMEOUT, allow_redirects=True)
        ct = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ct not in ALLOWED_CONTENT_TYPES:
            return base_score - 0.3
        cl = resp.headers.get("Content-Length")
        if cl and cl.isdigit():
            size = int(cl)
            if size < 30_000:
                return base_score - 0.4
            if size > 15_000_000:
                return base_score - 0.2
        return base_score + 0.1
    except Exception:
        return base_score - 0.1

def choose_best_candidate(candidates: List[ImageCandidate]) -> Optional[ImageCandidate]:
    if not candidates:
        return None
    rescored: List[Tuple[float, ImageCandidate]] = []
    for c in candidates[:12]:  # не перегружаем внешние сервисы
        s = score_candidate_by_head(c.url, c.score)
        rescored.append((s, c))
    rescored.sort(key=lambda x: x[0], reverse=True)
    return rescored[0][1] if rescored else None

# --- Скачивание и обработка ---
def process_image_to_jpeg(data: bytes) -> Tuple[bytes, int, int]:
    with Image.open(io.BytesIO(data)) as im:
        # Безопасный EXIF-поворот
        im = ImageOps.exif_transpose(im)
        # Конвертация в RGB (убрать альфу/CMYK)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        # Проверка минимального размера
        w, h = im.size
        if w < MIN_WIDTH or h < MIN_HEIGHT:
            raise ValueError(f"Image too small: {w}x{h}")

        # Масштабирование: max размер стороны = MAX_DIM
        scale = min(MAX_DIM / w, MAX_DIM / h, 1.0)
        if scale < 1.0:
            im = im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        # Сохранение в JPEG (прогрессивный)
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
        out.seek(0)
        w2, h2 = im.size
        return out.read(), w2, h2

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

# --- Telegram ---
def send_photo_file(
    bot_token: str,
    chat_id: str,
    photo_bytes: bytes,
    filename: str,
    caption_md_v2: Optional[str] = None,
    disable_notification: bool = False,
) -> dict:
    url = f"{TELEGRAM_API_URL}/bot{bot_token}/sendPhoto"
    files = {
        "photo": (filename, io.BytesIO(photo_bytes), "image/jpeg"),
    }
    data = {
        "chat_id": chat_id,
        "disable_notification": "true" if disable_notification else "false",
    }
    if caption_md_v2:
        data["caption"] = caption_md_v2
        data["parse_mode"] = "MarkdownV2"
    resp = _session.post(url, data=data, files=files, timeout=_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"Telegram sendPhoto error {resp.status_code}: {resp.text}")
    return resp.json()

# --- Публичная функция: прикрепить изображение к новости ---
def attach_image_for_news(
    article_url: str,
    title: str,
    caption: str,
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> dict:
    """
    1) Скачивает HTML статьи
    2) Извлекает кандидатов изображений
    3) Выбирает лучший, скачивает и нормализует
    4) Отправляет в Telegram как файл (JPEG)
    """
    bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.getenv("TARGET_CHAT_ID")
    if not bot_token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TARGET_CHAT_ID не заданы")

    logger.info("Fetching HTML: %s", article_url)
    html = fetch_html(article_url)

    logger.info("Extracting image candidates…")
    candidates = extract_image_candidates(html, base_url=article_url)
    if not candidates:
        raise RuntimeError("Кандидаты изображений не найдены")

    best = choose_best_candidate(candidates)
    if not best:
        raise RuntimeError("Не удалось выбрать подходящее изображение")

    logger.info("Downloading: %s", best.url)
    payload = images.download_image(best.url, referer=article_url)
    if not payload:
        raise RuntimeError("Не удалось скачать изображение")
    raw_bytes, _ct = payload

    logger.info("Processing image to JPEG…")
    jpg_bytes, w, h = process_image_to_jpeg(raw_bytes)
    digest = sha256_bytes(jpg_bytes)[:12]
    filename = f"news_{digest}_{w}x{h}.jpg"

    # Подпись: заголовок + ссылка (по желанию)
    # Экономим лимит 1024 и экранируем
    full_caption = f"{title}\n\n{article_url}"
    caption_final = clamp_caption(full_caption, 1024)
    caption_final = escape_md_v2(caption_final)

    logger.info("Sending to Telegram chat_id=%s", chat_id)
    res = send_photo_file(
        bot_token=bot_token,
        chat_id=chat_id,
        photo_bytes=jpg_bytes,
        filename=filename,
        caption_md_v2=caption_final,
    )
    logger.info("Sent: %s", res.get("ok"))
    return res

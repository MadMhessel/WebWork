import logging
import math
import requests
from typing import Optional

logger = logging.getLogger(__name__)

# Экранируем MarkdownV2 (минимально — символы, ломающие parse_mode)
_TELEGRAM_MD_V2_SPECIALS = r'_\*\[\]\(\)~`>#+\-=|{}\.!'

def escape_markdown_v2(text: str) -> str:
    out = []
    for ch in text:
        if ch in _TELEGRAM_MD_V2_SPECIALS:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)

def _truncate(s: str, limit: int) -> str:
    return s if len(s) <= limit else s[:limit-1] + "…"

def send_post(
    *,
    token: str,
    chat_id: str | int,
    text_md: str,
    image_bytes: Optional[bytes] = None,
    image_mime: str = "image/jpeg",
) -> None:
    """
    Универсальная отправка:
    - есть image_bytes -> sendPhoto с caption (<=1024), остаток текстом отдельным сообщением
    - нет image_bytes -> sendMessage
    """
    api = f"https://api.telegram.org/bot{token}"

    if image_bytes:
        caption = _truncate(text_md, 1024)
        files = {"photo": ("image.jpg", image_bytes, image_mime)}
        data = {
            "chat_id": chat_id,
            "caption": caption,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        }
        r = requests.post(f"{api}/sendPhoto", data=data, files=files, timeout=30)
        if not r.ok:
            logger.error("sendPhoto failed: %s %s", r.status_code, r.text)
            # fallback — попробуем отправить без картинки
            data2 = {
                "chat_id": chat_id,
                "text": text_md,
                "parse_mode": "MarkdownV2",
                "disable_web_page_preview": False,
            }
            r2 = requests.post(f"{api}/sendMessage", data=data2, timeout=30)
            r2.raise_for_status()
            return

        # если текст длиннее 1024 — досылаем остаток отдельным постом
        if len(text_md) > 1024:
            rest = text_md[1024:]
            data3 = {
                "chat_id": chat_id,
                "text": rest,
                "parse_mode": "MarkdownV2",
                "disable_web_page_preview": True,
            }
            r3 = requests.post(f"{api}/sendMessage", data=data3, timeout=30)
            r3.raise_for_status()
    else:
        data = {
            "chat_id": chat_id,
            "text": text_md,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": False,
        }
        r = requests.post(f"{api}/sendMessage", data=data, timeout=30)
        r.raise_for_status()

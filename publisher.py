import html, logging, time, json
from io import BytesIO
from typing import Optional, Any, Dict, Tuple, List
import requests
from . import config, rewrite, db
from .utils import shorten_url

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org"
_client_base_url: Optional[str] = None


def init_telegram_client(token: Optional[str] = None) -> None:
    """Инициализация клиентского базового URL для Telegram Bot API."""
    global _client_base_url
    token = (token or config.BOT_TOKEN or "").strip()
    if not token:
        logger.warning("BOT_TOKEN пуст — отправка в Telegram отключена.")
        _client_base_url = None
        return
    _client_base_url = f"{_API_BASE}/bot{token}"
    logger.info("Telegram клиент инициализирован.")


def _ensure_client() -> bool:
    if _client_base_url is None:
        init_telegram_client()
    return _client_base_url is not None


# Зарезервированные символы Telegram MarkdownV2 (если вдруг включат этот parse_mode)
_MD_V2_RESERVED = "_*[]()~`>#+-=|{}.!\\"

def _escape_markdown_v2(text: str) -> str:
    if not text:
        return ""
    out = []
    for ch in text:
        out.append(f"\\{ch}" if ch in _MD_V2_RESERVED else ch)
    return "".join(out)

def _escape_url_md_v2(url: str) -> str:
    if not url:
        return ""
    return url.replace("(", "\\(").replace(")", "\\)").replace(" ", "%20")

def _escape_html(text: str) -> str:
    return html.escape(text or "", quote=True)


def _smart_trim(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    if max_chars <= 1:
        return text[:max_chars]
    cut = text[:max_chars].rstrip()
    for sep in ["\n", ". ", " ", ""]:
        pos = cut.rfind(sep)
        if pos > 0:
            trimmed = cut[:pos].rstrip()
            return (trimmed + "…") if trimmed else cut[:max_chars - 1] + "…"
    return cut[:max_chars - 1] + "…"


def _build_message_html(title: str, body: str, url: str) -> str:
    etitle = _escape_html(title)
    ebody = _escape_html(body)
    url_attr = _escape_html(url)
    url_text = _escape_html(url)
    link_line = f"Подробнее: <a href=\"{url_attr}\">{url_text}</a>"
    return f"<b>{etitle}</b>\n\n{ebody}\n\n{link_line}".strip()


def _build_message_markdown(title: str, body: str, url: str) -> str:
    t = _escape_markdown_v2(title)
    b = _escape_markdown_v2(body)
    u = _escape_url_md_v2(url)
    return f"*{t}*\n\n{b}\n\n[Подробнее]({u})".strip()


def _build_message(title: str, body: str, url: str, parse_mode: str) -> str:
    if (parse_mode or "").upper() == "MARKDOWNV2":
        return _build_message_markdown(title, body, url)
    return _build_message_html(title, body, url)


def _download_image(url: str, cfg=config) -> Optional[Tuple[BytesIO, str]]:
    """Скачивает изображение и возвращает BytesIO и MIME тип или None."""
    if not url:
        logger.debug("URL изображения отсутствует.")
        return None
    timeout = float(getattr(cfg, "IMAGE_DOWNLOAD_TIMEOUT", 10))
    max_bytes = int(getattr(cfg, "IMAGE_MAX_BYTES", 5 * 1024 * 1024))
    try:
        r = requests.get(url, timeout=timeout, stream=True)
        if r.status_code != 200:
            logger.debug("Загрузка изображения вернула статус %s", r.status_code)
            return None
        content_type = (r.headers.get("Content-Type") or "").split(";")[0].lower()
        if not content_type.startswith("image/"):
            logger.debug("Отказано: Content-Type %s", content_type)
            return None
        cl_header = r.headers.get("Content-Length")
        if cl_header and int(cl_header) > max_bytes:
            logger.debug("Отказано: заявленный размер %s превышает лимит %d", cl_header, max_bytes)
            return None
        data = BytesIO()
        for chunk in r.iter_content(8192):
            if not chunk:
                continue
            data.write(chunk)
            if data.tell() > max_bytes:
                logger.debug("Отказано: изображение превышает лимит %d байт", max_bytes)
                return None
        data.seek(0)
        logger.debug("Изображение скачано (%d байт, %s)", data.getbuffer().nbytes, content_type)
        return data, content_type
    except Exception as ex:
        logger.debug("Ошибка при загрузке изображения %s: %s", url, ex)
        return None


def _api_post(method: str, payload: Dict[str, Any], files: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if not _ensure_client():
        logger.warning("Telegram клиент не инициализирован — вызов %s пропущен.", method)
        return None
    url = f"{_client_base_url}/{method}"
    try:
        r = requests.post(url, data=payload, files=files, timeout=30)
        if r.status_code != 200:
            logger.error("Ошибка HTTP %s: %s %s", method, r.status_code, r.text)
            return None
        j = r.json()
        if not j.get("ok"):
            logger.error("Telegram %s ok=false: %s", method, r.text)
            return None
        return j
    except Exception as ex:
        logger.exception("Исключение при вызове Telegram %s: %s", method, ex)
        return None


def _send_text(chat_id: str, text: str, parse_mode: str, reply_markup: Optional[dict] = None) -> Optional[str]:
    """Возвращает message_id при успехе, иначе None."""
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": "true" if config.TELEGRAM_DISABLE_WEB_PAGE_PREVIEW else "false",
    }
    if reply_markup is not None:
        payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    j = _api_post("sendMessage", payload)
    if not j:
        return None
    return str(j.get("result", {}).get("message_id"))


def _send_photo_file(chat_id: str, image: BytesIO, mime: str, caption: str, parse_mode: str) -> Optional[str]:
def send_message(chat_id: str, text: str, cfg=config) -> Optional[str]:
    """Send a simple text message. Returns message_id or None."""
    parse_mode = (cfg.TELEGRAM_PARSE_MODE or "HTML").upper()
    return _send_text(chat_id, text, parse_mode)


def _send_photo(chat_id: str, image: BytesIO, mime: str, caption: str, parse_mode: str) -> Optional[str]:
    """Возвращает message_id при успехе, иначе None."""
    payload: Dict[str, Any] = {"chat_id": chat_id, "caption": caption, "parse_mode": parse_mode}
    files = {"photo": ("image", image, mime)}
    j = _api_post("sendPhoto", payload, files=files)
    if not j:
        return None
    return str(j.get("result", {}).get("message_id"))


def _edit_message_text(chat_id: str, message_id: str, text: str, parse_mode: str, reply_markup: Optional[dict] = None) -> bool:
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": "true" if config.TELEGRAM_DISABLE_WEB_PAGE_PREVIEW else "false",
    }
    if reply_markup is not None:
        payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    j = _api_post("editMessageText", payload)
    return bool(j)


def answer_callback_query(callback_query_id: str, text: Optional[str] = None, show_alert: bool = False) -> bool:
    payload: Dict[str, Any] = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    if show_alert:
        payload["show_alert"] = "true"
    j = _api_post("answerCallbackQuery", payload)
    return bool(j)


def _send_photo(chat_id: str, photo: str, caption: str, parse_mode: str) -> Optional[Tuple[str, Optional[str]]]:
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "photo": photo,
def _send_photo(chat_id: str, photo_id: str, caption: str, parse_mode: str, reply_markup: Optional[dict] = None) -> Optional[str]:
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "photo": photo_id,
        "caption": caption,
        "parse_mode": parse_mode,
    }
    if reply_markup is not None:
        payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    j = _api_post("sendPhoto", payload)
    if not j:
        return None
    result = j.get("result", {})
    mid = str(result.get("message_id"))
    photos = result.get("photo") or []
    file_id = None
    if photos:
        file_id = photos[-1].get("file_id")
    return mid, file_id


def _send_media_group(chat_id: str, file_ids: List[str], caption: str, parse_mode: str) -> bool:
    media = []
    for i, fid in enumerate(file_ids):
        obj: Dict[str, Any] = {"type": "photo", "media": fid}
        if i == 0 and caption:
            obj["caption"] = caption
            obj["parse_mode"] = parse_mode
        media.append(obj)
    payload: Dict[str, Any] = {"chat_id": chat_id, "media": json.dumps(media, ensure_ascii=False)}
    j = _api_post("sendMediaGroup", payload)
    return bool(j)


def publish_message(chat_id: str, title: str, body: str, url: str, image_url: Optional[str] = None, cfg=config) -> bool:
    """
    Публикует сообщение. True — при успехе (получен message_id), False — при ошибке.
    """
    if not chat_id:
        logger.warning("chat_id пуст — отправка пропущена.")
        return False

    parse_mode = (cfg.TELEGRAM_PARSE_MODE or "HTML").upper()
    limit = int(cfg.TELEGRAM_MESSAGE_LIMIT or 4096)

    # Переписываем текст перед отправкой
    item = {"title": title, "content": body, "url": url}
    rewritten = rewrite.maybe_rewrite_item(item, cfg)
    body_current = rewritten.get("content", "") or ""
    message = _build_message(title or "", body_current, url or "", parse_mode)

    max_attempts = 4
    attempt = 0
    while len(message) > limit and attempt < max_attempts:
        overflow = len(message) - limit
        cut_by = max(overflow + 32, 64)
        target_len = max(0, len(body_current) - cut_by)
        body_current = _smart_trim(body_current, target_len)
        message = _build_message(title or "", body_current, url or "", parse_mode)
        attempt += 1

    if len(message) > limit:
        allowed_for_body = max(0, len(body_current) - (len(message) - limit + 32))
        body_current = _smart_trim(body_current, allowed_for_body)
        message = _build_message(title or "", body_current, url or "", parse_mode)

    if image_url:
        logger.debug("Картинка для публикации: %s", shorten_url(image_url))
        try:
            res = _send_photo(chat_id, image_url, message, parse_mode)
            if res:
                mid, _ = res
                logger.info(
                    "Сообщение с картинкой отправлено: chat_id=%s, message_id=%s, len=%d",
                    chat_id,
                    mid,
                    len(message),
                )
                slp = float(cfg.PUBLISH_SLEEP_BETWEEN_SEC or 0)
                if slp > 0:
                    time.sleep(slp)
                return True
            logger.warning(
                "Отказ публикации картинки %s: Telegram не вернул message_id",
                shorten_url(image_url),
            )
        except Exception as ex:
            logger.warning(
                "Отказ публикации картинки %s: %s",
                shorten_url(image_url),
                ex,
            )

    policy = (cfg.ON_SEND_ERROR or "retry").lower()
    retries = int(cfg.PUBLISH_MAX_RETRIES or 0) if policy == "retry" else 0
    backoff = float(cfg.RETRY_BACKOFF_SECONDS or 0)

    send_attempt = 0
    while True:
        send_attempt += 1
        mid = _send_text(chat_id, message, parse_mode)
        if mid:
            logger.info("Сообщение отправлено: chat_id=%s, message_id=%s, len=%d", chat_id, mid, len(message))
            slp = float(cfg.PUBLISH_SLEEP_BETWEEN_SEC or 0)
            if slp > 0:
                time.sleep(slp)
            return True

        logger.warning("Не удалось отправить сообщение (попытка %d/%d).", send_attempt, retries + 1)
        if policy == "retry" and send_attempt <= retries:
            time.sleep(backoff)
            continue

        if policy == "raise":
            try:
                raise RuntimeError("Ошибка публикации: Telegram не вернул message_id.")
            finally:
                return False

        logger.error("Публикация пропущена после ошибки.")
        return False


def publish_item(item: Dict[str, Any], cfg=config) -> bool:
    chat_id = str(cfg.CHANNEL_ID or "")
    title = item.get("title") or ""
    body = item.get("content") or ""
    url = item.get("url") or ""
    image_url = item.get("image_url") or ""
    return publish_message(chat_id, title, body, url, image_url=image_url, cfg=cfg)


def publish_to_channel(item_id: int, text_override: Optional[str] = None, cfg=config) -> Optional[str]:
    """Публикует элемент из moderation_queue в канал.

    Возвращает channel_message_id при успехе, иначе None. Повторные вызовы
    не создают дубль, а возвращают уже сохранённый message_id.
    """
    conn = db.connect()
    cur = conn.execute("SELECT * FROM moderation_queue WHERE id = ?", (item_id,))
    row = cur.fetchone()
    if not row:
        logger.error("mod_id=%s не найден в moderation_queue", item_id)
        return None
    row = dict(row)

    existing = row.get("channel_message_id")
    if existing:
        conn.close()
        return str(existing)

    chat_id = str(cfg.CHANNEL_ID or "")
    if not chat_id:
        logger.error("CHANNEL_ID пуст — публикация невозможна")
        return None

    title = row.get("title") or ""
    body = text_override if text_override is not None else (row.get("content") or "")
    url = row.get("url") or ""
    image_url = row.get("image_url") or ""
    parse_mode = (cfg.TELEGRAM_PARSE_MODE or "HTML").upper()

    item = {"title": title, "content": body, "url": url}
    rewritten = rewrite.maybe_rewrite_item(item, cfg)
    body_current = rewritten.get("content", "") or ""
    message = _build_message(title or "", body_current, url or "", parse_mode)

    cache = conn.execute(
        "SELECT tg_file_id, channel_message_id FROM images_cache WHERE item_id = ?",
        (item_id,),
    ).fetchone()
    if cache and cache["channel_message_id"]:
        conn.close()
        return str(cache["channel_message_id"])
    tg_file_id = cache["tg_file_id"] if cache else None

    retries = int(getattr(cfg, "RETRY_LIMIT", 3))
    delay = 1.0
    mid: Optional[str] = None
    for attempt in range(retries):
        try:
            if image_url:
                photo = tg_file_id or image_url
                res = _send_photo(chat_id, photo, message, parse_mode)
                if res:
                    mid, new_file_id = res
                    if new_file_id:
                        tg_file_id = new_file_id
                    break
            else:
                mid = _send_text(chat_id, message, parse_mode)
                if mid:
                    break
        except Exception as ex:
            logger.warning("Ошибка отправки в канал: %s", ex)
        time.sleep(delay)
        delay *= 2

    if not mid:
        logger.error("Не удалось отправить сообщение mod_id=%s", item_id)
        conn.close()
        return None

    conn.execute(
        "INSERT INTO images_cache (item_id, tg_file_id, channel_message_id) VALUES (?, ?, ?) "
        "ON CONFLICT(item_id) DO UPDATE SET tg_file_id=COALESCE(excluded.tg_file_id, tg_file_id), "
        "channel_message_id=excluded.channel_message_id",
        (item_id, tg_file_id, mid),
    )
    conn.execute(
        "UPDATE moderation_queue SET channel_message_id = ? WHERE id = ?",
        (mid, item_id),
    )
    conn.commit()
    conn.close()
    return mid
                caption = f"{_escape_html(title)}\n\n{_escape_html(url)}"
            mid = _send_photo_file(chat_id, img_data, mime, caption, parse_mode)
            if mid:
                logger.info(
                    "Фото отправлено: chat_id=%s, message_id=%s, bytes=%d", chat_id, mid, img_data.getbuffer().nbytes
                )
                slp = float(cfg.PUBLISH_SLEEP_BETWEEN_SEC or 0)
                if slp > 0:
                    time.sleep(slp)
                return True
            logger.debug("Отправка фото не удалась, fallback на текст.")
        else:
            logger.debug("Изображение не загружено, fallback на текст.")
    else:
        if not getattr(cfg, "ALLOW_IMAGES", False):
            logger.debug("Отправка изображений отключена.")
        elif not image_url:
            logger.debug("image_url отсутствует, отправляем текст.")

    return publish_message(chat_id, title, body, url, cfg=cfg)


def publish(item: Dict[str, Any], cfg=config) -> bool:
    """Публикует новость, извлекая данные из словаря."""
    return publish_item(item, cfg=cfg)






def send_moderation_preview(
    chat_id: str,
    mod_title: str,
    title: str,
    body: str,
    url: str,
    mod_id: int,
    images: Optional[List[str]] = None,
    cfg=config,
) -> Optional[str]:
    """Отправляет предпросмотр новости модератору с кнопками и картинками."""

    parse_mode = (cfg.TELEGRAM_PARSE_MODE or "HTML").upper()
    item = {"title": title, "content": body, "url": url}
    rewritten = rewrite.maybe_rewrite_item(item, cfg)
    body_rewritten = rewritten.get("content", "") or ""

    if parse_mode == "MARKDOWNV2":
        header = f"*{_escape_markdown_v2(mod_title)}*"
    else:
        header = f"<b>{_escape_html(mod_title)}</b>"

    def _build_full(limit: int) -> str:
        body_current = body_rewritten
        preview = _build_message(title, body_current, url, parse_mode)
        text = f"{header}\n\n{preview}".strip()
        attempt = 0
        while len(text) > limit and attempt < 4:
            overflow = len(text) - limit
            cut_by = max(overflow + 32, 64)
            target_len = max(0, len(body_current) - cut_by)
            body_current = _smart_trim(body_current, target_len)
            preview = _build_message(title, body_current, url, parse_mode)
            text = f"{header}\n\n{preview}".strip()
            attempt += 1
        if len(text) > limit:
            allowed = max(0, len(body_current) - (len(text) - limit + 32))
            body_current = _smart_trim(body_current, allowed)
            preview = _build_message(title, body_current, url, parse_mode)
            text = f"{header}\n\n{preview}".strip()
        return text

    message_text = _build_full(int(getattr(cfg, "TELEGRAM_MESSAGE_LIMIT", 4096)))
    caption_text = _build_full(1024)

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ Publish", "callback_data": f"publish:{mod_id}"},
                {"text": "❌ Reject", "callback_data": f"reject:{mod_id}"},
            ],
            [
                {"text": "😴 Snooze", "callback_data": f"snooze:{mod_id}"},
                {"text": "✏️ Edit", "callback_data": f"edit:{mod_id}"},
            ],
            [
                {"text": "🔗 Source", "url": url},
                {"text": "✅ Одобрить", "callback_data": f"approve:{mod_id}"},
                {"text": "❌ Отклонить", "callback_data": f"reject:{mod_id}"},
            ],
            [
                {"text": "🕐 Отложить", "callback_data": f"snooze:{mod_id}"},
                {"text": "✏️ Править", "callback_data": f"edit:{mod_id}"},
            ],
        ]
    }

    imgs = [i for i in (images or []) if i]
    if imgs:
        if len(imgs) > 1 and getattr(cfg, "ALLOW_MEDIA_GROUPS", False):
            ok = _send_media_group(chat_id, imgs, caption_text, parse_mode)
            if not ok:
                return None
            mid = _send_text(chat_id, message_text, parse_mode, reply_markup=reply_markup)
            if mid:
                logger.info(
                    "Модерация отправлена: chat_id=%s, message_id=%s, mod_id=%d (media group)",
                    chat_id,
                    mid,
                    mod_id,
                )
            return mid
        else:
            mid = _send_photo(chat_id, imgs[0], caption_text, parse_mode, reply_markup=reply_markup)
            if mid:
                logger.info(
                    "Модерация отправлена: chat_id=%s, message_id=%s, mod_id=%d (photo)",
                    chat_id,
                    mid,
                    mod_id,
                )
            return mid

    mid = _send_text(chat_id, message_text, parse_mode, reply_markup=reply_markup)
    if mid:
        logger.info("Модерация отправлена: chat_id=%s, message_id=%s, mod_id=%d", chat_id, mid, mod_id)
    return mid



def edit_moderation_message(chat_id: str, message_id: str, text: str, cfg=config) -> bool:
    parse_mode = (cfg.TELEGRAM_PARSE_MODE or "HTML").upper()
    return _edit_message_text(chat_id, message_id, text, parse_mode, reply_markup=None)

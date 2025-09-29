from __future__ import annotations

import asyncio
import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

from telethon.tl.custom.message import Message
from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto

try:  # pragma: no cover - optional import for package mode
    import config
except ImportError:  # pragma: no cover - direct execution
    import config  # type: ignore

from teleapi_client import fetch_bulk_channels, get_mtproto_client, normalize_telegram_link
from telegram_web import fetch_latest as web_fetch_latest
from webwork.utils.formatting import TG_TEXT_LIMIT, safe_format

log = logging.getLogger(__name__)


@dataclass(slots=True)
class TelegramPost:
    title: str
    text: str
    url: str
    media: Optional[str]
    source: str
    ts: str
    dedup_key: str
    alias: str

    def as_item(self) -> Dict[str, Any]:
        payload = {
            "title": self.title,
            "text": self.text,
            "url": self.url,
            "media": self.media,
            "source": self.source,
            "ts": self.ts,
            "dedup_key": self.dedup_key,
            # Backwards compatibility for the main pipeline expecting these keys
            "content": self.text,
            "summary": "",
            "guid": self.dedup_key,
            "published_at": self.ts,
            "source_id": f"tg:{self.alias}",
        }
        return payload


def _enforce_limit(text: str, limit: int) -> str:
    payload = (text or "").strip()
    formatted = safe_format(payload, getattr(config, "TELEGRAM_PARSE_MODE", "HTML"))
    if len(formatted) <= limit:
        return payload
    return payload[: max(0, limit - 1)].rstrip() + "…"


def _message_to_post(message: Message, alias: str) -> TelegramPost:
    text = (message.message or "").strip()
    title = text.split("\n", 1)[0] if text else f"Сообщение {message.id}"
    url = getattr(message, "link", None) or f"https://t.me/{alias}/{message.id}"
    published = ""
    if message.date:
        try:
            published = message.date.astimezone(dt.timezone.utc).isoformat()
        except Exception:  # pragma: no cover - defensive fallback
            try:
                published = message.date.isoformat()
            except Exception:
                published = ""
    media_type: Optional[str] = None
    if isinstance(message.media, MessageMediaPhoto):
        media_type = "photo"
    elif isinstance(message.media, MessageMediaDocument):
        if getattr(message.media, "video", None) or getattr(message, "video", None):
            media_type = "video"
        else:
            media_type = "document"
    trimmed_text = _enforce_limit(text, TG_TEXT_LIMIT)
    post = TelegramPost(
        title=_enforce_limit(title, TG_TEXT_LIMIT),
        text=trimmed_text,
        url=url,
        media=media_type,
        source=f"t.me/{alias}",
        ts=published,
        dedup_key=f"tg:{alias}:{message.id}",
        alias=alias,
    )
    return post


def _web_item_to_post(item: Dict[str, Any]) -> TelegramPost:
    alias = normalize_telegram_link(item.get("tg_alias") or item.get("source") or "") or ""
    title = (item.get("title") or "").strip()
    text = (item.get("content") or "").strip()
    published = (item.get("published_at") or "").strip()
    url = (item.get("url") or "").strip()
    if alias:
        dedup_key = f"tg:{alias}:{item.get('tg_msg_id') or ''}".rstrip(":")
    else:
        dedup_key = item.get("guid") or (item.get("url") or "")
    post = TelegramPost(
        title=_enforce_limit(title, TG_TEXT_LIMIT),
        text=_enforce_limit(text, TG_TEXT_LIMIT),
        url=url,
        media=None,
        source=f"t.me/{alias}" if alias else (item.get("source") or ""),
        ts=published,
        dedup_key=str(dedup_key),
        alias=alias,
    )
    return post


def _load_aliases(path: str) -> List[str]:
    file_path = Path(path)
    if not file_path.exists():
        log.warning("Telegram: файл со ссылками не найден: %s", file_path)
        return []
    aliases: List[str] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        alias = normalize_telegram_link(stripped)
        if alias:
            aliases.append(alias)
    unique_aliases = sorted(dict.fromkeys(aliases))
    log.info("Telegram: загружено %d каналов", len(unique_aliases))
    return unique_aliases


async def _fetch_mtproto_async(aliases: Iterable[str], limit: int) -> List[TelegramPost]:
    api_id = getattr(config, "TELETHON_API_ID", 0)
    api_hash = getattr(config, "TELETHON_API_HASH", "")
    session = getattr(config, "TELETHON_SESSION_NAME", "webwork_telethon")
    if api_id <= 0 or not api_hash:
        raise RuntimeError("TELETHON_API_ID/TELETHON_API_HASH не заданы")
    client = get_mtproto_client(api_id, api_hash, session)
    async with client:
        messages_by_alias = await fetch_bulk_channels(client, aliases, limit)
    posts: List[TelegramPost] = []
    for alias, messages in messages_by_alias.items():
        for message in messages:
            posts.append(_message_to_post(message, alias))
    return posts


def fetch_from_telegram(mode: str, links_file: str, limit: int) -> List[Dict[str, Any]]:
    aliases = _load_aliases(links_file)
    if not aliases:
        return []
    mode_normalized = (mode or "mtproto").strip().lower()
    if mode_normalized == "mtproto":
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            posts = loop.run_until_complete(_fetch_mtproto_async(aliases, limit))
        finally:
            try:
                loop.close()
            except Exception:  # pragma: no cover - cleanup guard
                pass
    elif mode_normalized == "web":
        posts = []
        for alias in aliases:
            try:
                items = web_fetch_latest(alias, limit=limit)
            except Exception as exc:  # pragma: no cover - network errors
                log.warning("Telegram web fetch error for %s: %s", alias, exc)
                continue
            for item in items:
                posts.append(_web_item_to_post(item))
    else:
        raise ValueError(f"Unknown telegram mode: {mode}")
    log.info("Telegram: получено %d сообщений (mode=%s)", len(posts), mode_normalized)
    return [post.as_item() for post in posts]


def fetch_posts_iterator(mode: str, links_file: str, limit: int) -> Iterator[Dict[str, Any]]:
    for item in fetch_from_telegram(mode, links_file, limit):
        yield item

from __future__ import annotations
import asyncio
import datetime as dt
import logging
import os
import re
from typing import AsyncIterator, Dict, Iterator, List, Optional

from telethon import TelegramClient
from telethon.tl.types import Message

log = logging.getLogger("app")

API_ID = int(os.getenv("TELETHON_API_ID", "0"))
API_HASH = os.getenv("TELETHON_API_HASH", "")
SESSION_NAME = os.getenv("TELETHON_SESSION_NAME", "webwork_telethon")

TELEGRAM_LINKS_FILE = os.getenv("TELEGRAM_LINKS_FILE", "telegram_links.txt").strip()

_ALIAS_RE = re.compile(r"(?:https?://)?t\.me/(?:s/)?(@?[\w\d_+]+)")

def _normalize_tme(url: str) -> Optional[str]:
    s = (url or "").strip()
    if not s:
        return None
    m = _ALIAS_RE.search(s)
    if not m:
        return None
    alias = m.group(1).lstrip("@")
    return alias

def load_aliases_from_file(path: str) -> List[str]:
    if not os.path.exists(path):
        log.warning("TG: файл со ссылками не найден: %s", path)
        return []
    aliases: List[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            alias = _normalize_tme(s)
            if alias:
                aliases.append(alias)
    aliases = sorted(set(aliases))
    log.info("TG: загружено %d источников", len(aliases))
    return aliases

async def _iter_channel_messages(client: TelegramClient, alias: str, limit: int = 50) -> AsyncIterator[Message]:
    async for msg in client.iter_messages(alias, limit=limit):
        # пропускаем сервисные сообщения
        if not msg or not (msg.message or msg.media):
            continue
        yield msg

def _message_to_item(msg: Message, alias: str) -> Dict:
    title = (msg.message or "").strip().split("\n", 1)[0]
    content = (msg.message or "").strip()
    url = ""
    if msg.link:
        url = msg.link  # публичные каналы дают t.me/c/... или t.me/<alias>/<id>
    published = ""
    try:
        if msg.date:
            # убедимся, что это ISO-строка в UTC
            published = msg.date.astimezone(dt.timezone.utc).isoformat()
    except Exception:
        published = ""
    # унифицируем «новостной» словарь под текущий pipeline
    return {
        "source": f"t.me/{alias}",
        "source_id": f"tg:{alias}",
        "guid": f"tg:{alias}:{msg.id}",
        "url": url,
        "title": title,
        "content": content,
        "summary": "",
        "published_at": published,
        "tags": [],
    }

async def fetch_telegram_items_async(aliases: List[str], per_channel_limit: int = 30) -> List[Dict]:
    if API_ID <= 0 or not API_HASH:
        raise RuntimeError("TELETHON_API_ID/TELETHON_API_HASH не заданы")
    items: List[Dict] = []
    async with TelegramClient(SESSION_NAME, API_ID, API_HASH) as client:
        for alias in aliases:
            try:
                async for msg in _iter_channel_messages(client, alias, limit=per_channel_limit):
                    items.append(_message_to_item(msg, alias))
            except Exception as e:
                log.error("TG: ошибка чтения %s: %s", alias, e)
    return items

def fetch_telegram_items(aliases: List[str], per_channel_limit: int = 30) -> Iterator[Dict]:
    """Синхронная обёртка для использования в текущем run_once()."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        res = loop.run_until_complete(fetch_telegram_items_async(aliases, per_channel_limit))
        for it in res:
            yield it
    finally:
        try:
            loop.close()
        except Exception:
            pass

from __future__ import annotations

import asyncio
import logging
import os
from datetime import timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from telethon import TelegramClient
from telethon.errors import RPCError
from telethon.tl.types import Message

import config

logger = logging.getLogger(__name__)

_ALIAS_RE = None


def _alias_pattern():
    global _ALIAS_RE
    if _ALIAS_RE is None:
        import re

        _ALIAS_RE = re.compile(r"(?:https?://)?t\.me/(?:s/)?(@?[\w\d_+\-]+)")
    return _ALIAS_RE


def _normalize_alias(value: str) -> Optional[str]:
    if not value:
        return None
    match = _alias_pattern().search(value.strip())
    if not match:
        return None
    return match.group(1).lstrip("@").lower()


def _load_aliases(path: Path) -> List[str]:
    if not path.exists():
        logger.warning("TG-MTP: файл со списком каналов не найден: %s", path)
        return []
    aliases: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        alias = _normalize_alias(stripped)
        if alias:
            aliases.append(alias)
    unique_aliases = sorted(dict.fromkeys(aliases))
    logger.info("TG-MTP: загружено %d каналов", len(unique_aliases))
    return unique_aliases


def _message_to_item(msg: Message, alias: str) -> Dict[str, object]:
    text = (msg.message or "").strip()
    title = text.split("\n", 1)[0] if text else f"Сообщение {msg.id}"
    url = ""
    if getattr(msg, "link", None):
        url = msg.link
    published = ""
    if msg.date:
        try:
            published = msg.date.astimezone(timezone.utc).isoformat()
        except Exception:
            try:
                published = msg.date.isoformat()
            except Exception:
                published = ""
    return {
        "source": f"t.me/{alias}",
        "source_id": f"tg:{alias}",
        "guid": f"tg:{alias}:{msg.id}",
        "url": url,
        "title": title,
        "content": text,
        "summary": "",
        "published_at": published,
        "source_domain": "t.me",
        "trust_level": 1,
    }


async def _fetch_alias(client: TelegramClient, alias: str, limit: int) -> List[Dict[str, object]]:
    items: List[Dict[str, object]] = []
    try:
        async for msg in client.iter_messages(alias, limit=limit):
            if not msg or not (msg.message or msg.media):
                continue
            items.append(_message_to_item(msg, alias))
    except RPCError as exc:
        logger.error("TG-MTP: RPC ошибка %s: %s", alias, exc)
    except Exception as exc:  # pragma: no cover - на всякий случай
        logger.exception("TG-MTP: неожиданная ошибка %s: %s", alias, exc)
    return items


async def _fetch_many(aliases: Iterable[str], limit: int) -> List[Dict[str, object]]:
    api_id = getattr(config, "TELETHON_API_ID", 0)
    api_hash = getattr(config, "TELETHON_API_HASH", "")
    if api_id <= 0 or not api_hash:
        raise RuntimeError("TELETHON_API_ID/TELETHON_API_HASH не заданы")

    session_name = os.getenv("TELETHON_SESSION_NAME", "webwork_telethon")
    items: List[Dict[str, object]] = []
    async with TelegramClient(session_name, api_id, api_hash) as client:
        for alias in aliases:
            alias_items = await _fetch_alias(client, alias, limit)
            items.extend(alias_items)
    return items


def fetch_from_file(path: str) -> List[Dict[str, object]]:
    aliases = _load_aliases(Path(path))
    if not aliases:
        return []
    limit = int(getattr(config, "TELEGRAM_FETCH_LIMIT", 30))
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(_fetch_many(aliases, limit))
    finally:
        try:
            loop.close()
        except Exception:
            pass

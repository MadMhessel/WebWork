from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import Iterable, List, Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError
from telethon.tl.custom.message import Message

logger = logging.getLogger(__name__)

_ALIAS_RE = re.compile(r"(?:https?://)?t\.me/(?:s/)?(@?[\w\d_+\-]+)")


def normalize_telegram_link(value: str) -> Optional[str]:
    """Return normalized Telegram alias from t.me link or ``@username``."""

    if not value:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    match = _ALIAS_RE.search(stripped)
    if match:
        alias = match.group(1)
    elif re.fullmatch(r"[\w\d_+\-]+", stripped):
        alias = stripped
    elif stripped.startswith("@") and re.fullmatch(r"@[\w\d_+\-]+", stripped):
        alias = stripped[1:]
    else:
        return None
    alias = alias.lstrip("@")
    if not alias:
        return None
    return alias


def get_mtproto_client(api_id: int, api_hash: str, session_name: str) -> TelegramClient:
    """Factory helper for a configured Telethon ``TelegramClient`` instance."""

    if api_id <= 0:
        raise ValueError("api_id must be positive")
    if not api_hash:
        raise ValueError("api_hash is required")
    session = session_name or "webwork_telethon"
    logger.debug("Creating Telethon client: session=%s", session)
    return TelegramClient(session, api_id, api_hash)


async def fetch_channel_messages(
    client: TelegramClient,
    link_or_username: str,
    limit: int,
) -> List[Message]:
    """Fetch messages from a Telegram channel/group using Telethon.

    Telethon автоматически обрабатывает небольшие ограничения скорости, однако
    при продолжительных FloodWait API поднимает исключение. Здесь мы ждём
    указанное время и повторяем запрос с экспоненциальным бэкоффом для других
    временных ошибок.
    """

    alias = normalize_telegram_link(link_or_username)
    if not alias:
        raise ValueError(f"Invalid Telegram link: {link_or_username!r}")
    limit = max(1, int(limit or 1))
    base_delay = 5.0
    attempt = 0
    max_attempts = 5

    while True:
        attempt += 1
        try:
            logger.debug("Fetching up to %s messages from %s", limit, alias)
            messages: List[Message] = []
            async for message in client.iter_messages(alias, limit=limit):
                if not message:
                    continue
                if not (message.message or message.media):
                    continue
                messages.append(message)
            return messages
        except FloodWaitError as exc:
            wait_seconds = max(1, int(getattr(exc, "seconds", 0) or 0))
            logger.warning(
                "TELEGRAM: FloodWait для %s на %s с — ожидание", alias, wait_seconds
            )
            await asyncio.sleep(wait_seconds)
            # FloodWait обнуляет счётчик попыток, так как это штатная пауза API.
            attempt = 0
        except (RPCError, asyncio.TimeoutError, ConnectionError) as exc:
            if attempt >= max_attempts:
                logger.exception(
                    "TELEGRAM: %s — ошибка после %s попыток: %s", alias, attempt, exc
                )
                raise
            wait = min(300.0, base_delay * (2 ** (attempt - 1)))
            jitter = random.uniform(0, wait * 0.1)
            delay = wait + jitter
            logger.warning(
                "TELEGRAM: временная ошибка для %s (%s), повтор через %.1f с",
                alias,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
        except Exception:
            # Неизвестные ошибки пробрасываем дальше — их должны обработать выше.
            raise


async def fetch_bulk_channels(
    client: TelegramClient,
    identifiers: Iterable[str],
    limit: int,
) -> dict[str, List[Message]]:
    """Fetch messages for multiple aliases with shared client."""

    result: dict[str, List[Message]] = {}
    for identifier in identifiers:
        alias = normalize_telegram_link(identifier)
        if not alias:
            logger.warning("TELEGRAM: skip invalid link %s", identifier)
            continue
        try:
            result[alias] = await fetch_channel_messages(client, alias, limit)
        except Exception as exc:  # pragma: no cover - network/telethon errors
            logger.exception("TELEGRAM: failed to fetch %s: %s", alias, exc)
            result.setdefault(alias, [])
    return result

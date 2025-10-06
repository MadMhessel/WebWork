from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import Iterable, List, Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError
from telethon.tl.custom.message import Message

from rate_limiter import TokenBucket

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


def get_mtproto_client(
    api_id: int,
    api_hash: str,
    session_name: str,
    *,
    flood_sleep_threshold: Optional[int] = None,
) -> TelegramClient:
    """Factory helper for a configured Telethon ``TelegramClient`` instance."""

    if api_id <= 0:
        raise ValueError("api_id must be positive")
    if not api_hash:
        raise ValueError("api_hash is required")
    session = session_name or "webwork_telethon"
    logger.debug("Creating Telethon client: session=%s", session)
    kwargs = {}
    if flood_sleep_threshold is not None:
        kwargs["flood_sleep_threshold"] = int(flood_sleep_threshold)
    return TelegramClient(session, api_id, api_hash, **kwargs)


async def fetch_channel_messages(
    client: TelegramClient,
    link_or_username: str,
    limit: int,
    *,
    bucket: Optional[TokenBucket] = None,
    max_attempts: int = 5,
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
    transient_delays = (0.5, 1.0, 2.0, 4.0)
    attempt = 0
    flood_retries = 0

    while attempt < max_attempts:
        attempt += 1
        try:
            if bucket is not None:
                await bucket.acquire()
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
            flood_retries += 1
            if flood_retries >= max_attempts:
                logger.error(
                    "TELEGRAM: %s — превышено число FloodWait (%s)", alias, max_attempts
                )
                raise
        except (RPCError, asyncio.TimeoutError, ConnectionError) as exc:
            if attempt >= max_attempts:
                logger.exception(
                    "TELEGRAM: %s — ошибка после %s попыток: %s", alias, attempt, exc
                )
                raise
            wait = transient_delays[min(attempt - 1, len(transient_delays) - 1)]
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
    *,
    concurrency: int = 5,
    bucket: Optional[TokenBucket] = None,
) -> dict[str, List[Message]]:
    """Fetch messages for multiple aliases with shared client."""

    result: dict[str, List[Message]] = {}
    sem = asyncio.Semaphore(max(1, int(concurrency)))

    async def _runner(identifier: str) -> tuple[Optional[str], List[Message]]:
        alias = normalize_telegram_link(identifier)
        if not alias:
            logger.warning("TELEGRAM: skip invalid link %s", identifier)
            return None, []
        try:
            async with sem:
                messages = await fetch_channel_messages(
                    client, alias, limit, bucket=bucket
                )
        except Exception as exc:  # pragma: no cover - network/telethon errors
            logger.exception("TELEGRAM: failed to fetch %s: %s", alias, exc)
            messages = []
        return alias, messages

    tasks = [asyncio.create_task(_runner(identifier)) for identifier in identifiers]
    for task in asyncio.as_completed(tasks):
        alias, messages = await task
        if alias is None:
            continue
        result[alias] = messages
    return result

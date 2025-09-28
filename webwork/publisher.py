"""Helpers for Telegram publishing with logging and chunking."""

from __future__ import annotations

import logging
from typing import Any, Iterable, Protocol

from . import telegram_cfg as _telegram_cfg_loader
from .logging_setup import log_kv
from .utils.formatting import (
    TG_CAPTION_LIMIT,
    TG_TEXT_LIMIT,
    chunk_text,
    safe_format,
)

logger = logging.getLogger("webwork.publisher")


class TelegramApi(Protocol):
    def sendMessage(self, chat_id: str, text: str, parse_mode: str | None = None, **kwargs: Any) -> Any:  # noqa: N802 - Telegram casing
        ...

    def sendPhoto(
        self,
        chat_id: str,
        photo: Any,
        caption: str | None = None,
        parse_mode: str | None = None,
        **kwargs: Any,
    ) -> Any:  # noqa: N802 - Telegram casing
        ...


def send_text(api: TelegramApi, chat_id: str, text: str) -> None:
    """Send text respecting Telegram chunk limits and log the result."""

    tg_cfg = _telegram_cfg_loader()
    payload = safe_format(text or "", tg_cfg.parse_mode)
    chunks = chunk_text(payload, TG_TEXT_LIMIT) or [payload[:TG_TEXT_LIMIT]] if payload else []
    if not chunks:
        chunks = [""]
    for idx, chunk in enumerate(chunks, 1):
        response = api.sendMessage(chat_id, chunk, parse_mode=tg_cfg.parse_mode)
        log_kv(
            logger,
            logging.INFO,
            "sent text",
            channel=chat_id,
            part=idx,
            parts=len(chunks),
            length=len(chunk),
            message_id=getattr(response, "message_id", None),
        )


def send_photo_with_caption(api: TelegramApi, chat_id: str, photo: Any, caption: str | None) -> None:
    """Send photo with caption, splitting tail text as separate messages."""

    tg_cfg = _telegram_cfg_loader()
    payload = safe_format(caption or "", tg_cfg.parse_mode)
    chunks = chunk_text(payload, TG_CAPTION_LIMIT)
    caption_text = chunks[0] if chunks else payload[:TG_CAPTION_LIMIT]
    response = api.sendPhoto(chat_id, photo=photo, caption=caption_text, parse_mode=tg_cfg.parse_mode)
    log_kv(
        logger,
        logging.INFO,
        "sent photo",
        channel=chat_id,
        caption_len=len(caption_text or ""),
        message_id=getattr(response, "message_id", None),
    )
    for idx, tail in enumerate(chunks[1:], 2):
        response_tail = api.sendMessage(chat_id, tail, parse_mode=tg_cfg.parse_mode)
        log_kv(
            logger,
            logging.INFO,
            "sent photo tail",
            channel=chat_id,
            part=idx,
            length=len(tail),
            message_id=getattr(response_tail, "message_id", None),
        )


def split_text(texts: Iterable[str]) -> list[str]:
    tg_cfg = _telegram_cfg_loader()
    result: list[str] = []
    for text in texts:
        formatted = safe_format(text, tg_cfg.parse_mode)
        result.extend(chunk_text(formatted, TG_TEXT_LIMIT))
    return result

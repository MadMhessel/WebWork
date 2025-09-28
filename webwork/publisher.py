"""Lightweight helpers for Telegram publishing respecting platform limits."""

from __future__ import annotations

from typing import Any, Iterable, Protocol

from . import telegram_cfg as _telegram_cfg_loader
from .utils.formatting import (
    TG_CAPTION_LIMIT,
    TG_TEXT_LIMIT,
    chunk_text,
    safe_format,
)


class TelegramApi(Protocol):
    def sendMessage(self, chat_id: str, text: str, parse_mode: str | None = None, **kwargs: Any) -> Any:  # noqa: N802 (Telegram casing)
        ...

    def sendPhoto(
        self,
        chat_id: str,
        photo: Any,
        caption: str | None = None,
        parse_mode: str | None = None,
        **kwargs: Any,
    ) -> Any:  # noqa: N802 (Telegram casing)
        ...


def send_text(api: TelegramApi, chat_id: str, text: str) -> None:
    """Send text respecting Telegram chunk limits."""

    tg_cfg = _telegram_cfg_loader()
    limit = TG_TEXT_LIMIT
    payload = safe_format(text or "", tg_cfg.parse_mode)
    for chunk in chunk_text(payload, limit) or [""]:
        api.sendMessage(chat_id, chunk, parse_mode=tg_cfg.parse_mode)


def send_photo_with_caption(api: TelegramApi, chat_id: str, photo: Any, caption: str | None) -> None:
    """Send photo with caption, splitting tail text as separate messages."""

    tg_cfg = _telegram_cfg_loader()
    limit = TG_CAPTION_LIMIT
    payload = safe_format(caption or "", tg_cfg.parse_mode)
    chunks = chunk_text(payload, limit)
    caption_text = chunks[0] if chunks else ""
    api.sendPhoto(chat_id, photo=photo, caption=caption_text, parse_mode=tg_cfg.parse_mode)
    for tail in chunks[1:]:
        api.sendMessage(chat_id, tail, parse_mode=tg_cfg.parse_mode)


def split_text(texts: Iterable[str]) -> list[str]:
    tg_cfg = _telegram_cfg_loader()
    result: list[str] = []
    for text in texts:
        formatted = safe_format(text, tg_cfg.parse_mode)
        result.extend(chunk_text(formatted, TG_TEXT_LIMIT))
    return result

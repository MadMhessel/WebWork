from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from rewriter.base import NewsItem
from formatting.telegram import escape_markdown_v2, split_to_telegram_chunks


@dataclass
class TelegramMedia:
    photo: Optional[str] = None
    caption: Optional[str] = None
    text_parts: List[str] = None


def build_caption(item: NewsItem, url: str, limit: int = 1024) -> str:
    base = f'**{item.title}**\n\n{item.text}\n\n[Источник]({url})'
    esc = escape_markdown_v2(base)
    if len(esc) <= limit:
        return esc
    over = len(esc) - limit
    body_limit = max(len(item.text) - over, 0)
    truncated = (
        f'**{escape_markdown_v2(item.title)}**\n\n'
        f'{escape_markdown_v2(item.text[:body_limit])}\n\n'
        f'[Источник]({escape_markdown_v2(url)})'
    )
    return truncated[:limit]


def build_text_messages(item: NewsItem, limit: int = 4096) -> List[str]:
    esc = escape_markdown_v2(item.text)
    return split_to_telegram_chunks(esc, limit=limit)

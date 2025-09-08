from __future__ import annotations

import re
from typing import List

_SPECIAL_CHARS = r"_*[]()~`>#+-=|{}.!"
_ESCAPE_RE = re.compile("([" + re.escape(_SPECIAL_CHARS) + "])" )


def escape_markdown_v2(text: str) -> str:
    """Escape Telegram MarkdownV2 special characters."""
    return _ESCAPE_RE.sub(r"\\\\\1", text)


def split_to_telegram_chunks(text: str, limit: int = 4096) -> List[str]:
    """Split text into chunks not exceeding Telegram limit.

    Prefer breaking on sentence or newline boundaries; fall back to words.
    """
    if len(text) <= limit:
        return [text]
    parts: List[str] = []
    rest = text
    while rest:
        if len(rest) <= limit:
            parts.append(rest.strip())
            break
        cut = rest.rfind("\n", 0, limit)
        if cut == -1:
            cut = rest.rfind(". ", 0, limit)
            if cut == -1:
                cut = rest.rfind(" ", 0, limit)
                if cut == -1:
                    cut = limit
        parts.append(rest[:cut].strip())
        rest = rest[cut:].lstrip()
    return [p for p in parts if p]

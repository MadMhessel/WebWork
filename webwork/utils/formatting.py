"""Formatting utilities that respect Telegram limits and escaping."""

from __future__ import annotations

import re
from typing import List

TG_TEXT_LIMIT = 4096
TG_CAPTION_LIMIT = 1024

_MD2_NEED_ESCAPE = r"[_*\[\]()~`>#+\-=|{}.!]"
_escape_regex = re.compile(f"({_MD2_NEED_ESCAPE})")


def escape_markdown_v2(text: str) -> str:
    """Escape characters that have special meaning in MarkdownV2."""

    return _escape_regex.sub(lambda match: "\\" + match.group(1), text)


def safe_format(text: str, parse_mode: str) -> str:
    """Return ``text`` escaped according to ``parse_mode`` rules."""

    parse = (parse_mode or "").strip().upper()
    if parse == "MARKDOWNV2":
        return escape_markdown_v2(text)
    return text


def _flush_chunk(parts: List[str]) -> str:
    chunk = "\n".join(parts).strip()
    return chunk


def chunk_text(text: str, limit: int) -> List[str]:
    """Split ``text`` into Telegram-safe chunks with ``limit`` characters."""

    if limit <= 0:
        raise ValueError("limit must be positive")
    if not text:
        return []

    result: List[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current:
            result.append(current.strip())
            current = ""

    for raw_line in text.split("\n"):
        line = raw_line.rstrip()
        addition = ("\n" if current else "") + line if line else ""
        candidate = current + addition
        if line and len(candidate) <= limit:
            current = candidate
            continue
        if line and not current:
            while line:
                segment = line[:limit]
                result.append(segment)
                line = line[limit:]
            current = ""
        elif line:
            flush()
            while line:
                if len(line) <= limit:
                    current = line
                    line = ""
                else:
                    result.append(line[:limit])
                    line = line[limit:]
        else:
            flush()
    flush()
    return [chunk for chunk in result if chunk]

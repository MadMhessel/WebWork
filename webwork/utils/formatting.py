"""Formatting utilities that respect Telegram limits and escaping."""

from __future__ import annotations

import re
from typing import List

TG_TEXT_LIMIT = 4096
TG_CAPTION_LIMIT = 1024

_MD2_NEED_ESCAPE = r"[_*\[\]()~`>#+\-=|{}.!]"
_ESCAPE_RE = re.compile(f"({_MD2_NEED_ESCAPE})")


def escape_markdown_v2(text: str) -> str:
    """Escape characters that have special meaning in MarkdownV2."""

    if not text:
        return ""
    return _ESCAPE_RE.sub(r"\\\1", text)


def safe_format(text: str, parse_mode: str) -> str:
    """Return ``text`` escaped according to ``parse_mode`` rules."""

    payload = text or ""
    if (parse_mode or "").strip().upper() == "MARKDOWNV2":
        return escape_markdown_v2(payload)
    return payload


def _split_long_line(line: str, limit: int) -> List[str]:
    if len(line) <= limit:
        return [line]
    chunks: List[str] = []
    start = 0
    while start < len(line):
        chunks.append(line[start : start + limit])
        start += limit
    return chunks


def chunk_text(text: str, limit: int) -> List[str]:
    """Split ``text`` into Telegram-safe chunks with ``limit`` characters."""

    if limit <= 0:
        raise ValueError("limit must be positive")
    if not text:
        return []

    parts: List[str] = []
    buffer = ""

    def flush() -> None:
        nonlocal buffer
        if buffer.strip():
            parts.append(buffer.strip())
        buffer = ""

    for raw_line in (text or "").split("\n"):
        line = raw_line.rstrip()
        segments = _split_long_line(line, limit) if line else [""]
        for idx, segment in enumerate(segments):
            candidate = segment
            if buffer and segment:
                candidate = f"{buffer}\n{segment}"
            elif buffer and not segment:
                candidate = buffer
            if segment and len(candidate) <= limit:
                buffer = candidate
                continue
            if segment and len(segment) <= limit and not buffer:
                buffer = segment
                continue
            if buffer:
                flush()
            if segment:
                if len(segment) <= limit:
                    buffer = segment
                else:
                    for chunk in _split_long_line(segment, limit):
                        parts.append(chunk)
                    buffer = ""
            elif idx == 0:
                flush()
        if not line:
            flush()

    flush()
    return [chunk for chunk in parts if chunk]

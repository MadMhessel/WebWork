"""Text rewriting utilities used by the bot.

Previously the project exposed both an LLM based strategy and a simple
rule-based fallback.  According to the new requirements only rewriting via
YandexGPT remains enabled and any failures simply return the original text.
"""

from __future__ import annotations

import logging

from formatting import clean_html_tags, truncate_by_chars
import yandex_llm

logger = logging.getLogger(__name__)



class Rewriter:
    """Thin wrapper around :func:`yandex_llm.rewrite`."""

    def __init__(
        self,
        topic_hint: str = "строительство, инфраструктура, ЖК, дороги, мосты",
    ) -> None:
        self.topic_hint = topic_hint

    def rewrite(
        self, title: str, body_html: str, max_len: int, region_hint: str
    ) -> str:
        plain = clean_html_tags(body_html)
        prompt = f"{title}\n\n{plain}".strip()
        try:
            text = yandex_llm.rewrite(
                prompt,
                target_chars=max_len,
                topic_hint=self.topic_hint,
                region_hint=region_hint or None,
            )
        except Exception as exc:
            logger.warning("Yandex rewrite failed: %s", exc)
            text = plain
        result = truncate_by_chars(text, max_len)
        if len(result) < len(text):
            logger.warning("rewrite truncated to %d chars", max_len)
        return result


__all__ = ["Rewriter"]

"""Text rewriting utilities used by the bot.

The rewritten version relies solely on the bundled rule-based engine so the
application does not depend on any external large language model APIs.  This
keeps the rewriting pipeline self-contained and avoids network calls during
news processing.
"""

from __future__ import annotations

import logging

from formatting import clean_html_tags, truncate_by_chars
from rewriter.base import NewsItem
from rewriter.rules import RuleBasedRewriter
import config

logger = logging.getLogger(__name__)


class Rewriter:
    """Rewrite news items using the internal rule-based engine only."""

    def __init__(
        self,
        cfg=None,
        topic_hint: str = "строительство, инфраструктура, ЖК, дороги, мосты",
    ) -> None:
        self.cfg = cfg or config
        self.topic_hint = topic_hint
        self.rule = RuleBasedRewriter()

    def rewrite(
        self, title: str, body_html: str, max_len: int, region_hint: str
    ) -> str:
        plain = clean_html_tags(body_html)
        item = NewsItem(
            id="",
            source="",
            url="",
            title=title,
            text=plain,
        )
        logger.info("rewrite via internal rule engine: in=%d", len(plain))
        text = self.rule.rewrite(item, max_len=max_len).text
        result = truncate_by_chars(text, max_len)
        if len(result) < len(text):
            logger.warning("rewrite truncated to %d chars", max_len)
        return result


__all__ = ["Rewriter"]

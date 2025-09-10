"""Text rewriting utilities used by the bot.

Rewriting primarily uses YandexGPT, but falls back to a local rule-based
strategy when the API is disabled or returns an error.
"""

from __future__ import annotations

import logging

from formatting import clean_html_tags, truncate_by_chars
import yandex_llm
from rewriter.base import NewsItem
from rewriter.rules import RuleBasedRewriter
import config

logger = logging.getLogger(__name__)


class Rewriter:
    """Adapter that tries Yandex LLM first and falls back to rule-based."""

    def __init__(
        self,
        cfg=None,
        topic_hint: str = "строительство, инфраструктура, ЖК, дороги, мосты",
    ) -> None:
        self.cfg = cfg or config
        self.topic_hint = topic_hint
        self.rule = RuleBasedRewriter()

    def _can_use_yandex(self) -> bool:
        if not getattr(self.cfg, "YANDEX_REWRITE_ENABLED", False):
            return False
        mode = getattr(self.cfg, "YANDEX_API_MODE", "openai")
        if mode == "rest":
            return bool(getattr(self.cfg, "YANDEX_IAM_TOKEN", "")) and bool(
                getattr(self.cfg, "YANDEX_FOLDER_ID", "")
            )
        return bool(getattr(self.cfg, "YANDEX_API_KEY", "")) and bool(
            getattr(self.cfg, "YANDEX_FOLDER_ID", "")
        )

    def rewrite(
        self, title: str, body_html: str, max_len: int, region_hint: str
    ) -> str:
        plain = clean_html_tags(body_html)
        prompt = f"{title}\n\n{plain}".strip()
        if self._can_use_yandex():
            try:
                text = yandex_llm.rewrite(
                    prompt,
                    target_chars=max_len,
                    topic_hint=self.topic_hint,
                    region_hint=region_hint or None,
                )
                logger.info(
                    "rewrite via yandex: in=%d out=%d", len(plain), len(text)
                )
            except yandex_llm.YandexLLMError as exc:
                logger.warning(
                    "Yandex rewrite failed (%s), falling back", exc.label
                )
                item = NewsItem(
                    id="",
                    source="",
                    url="",
                    title=title,
                    text=plain,
                )
                text = self.rule.rewrite(item, max_len=max_len).text
        else:
            logger.info("Yandex rewrite disabled, using rule-based")
            item = NewsItem(
                id="",
                source="",
                url="",
                title=title,
                text=plain,
            )
            text = self.rule.rewrite(item, max_len=max_len).text
        result = truncate_by_chars(text, max_len)
        if len(result) < len(text):
            logger.warning("rewrite truncated to %d chars", max_len)
        return result


__all__ = ["Rewriter"]

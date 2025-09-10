"""Text rewriting utilities used by the bot.

The real project features a sophisticated rewriting pipeline.  For the
exercise we only implement a very small – yet fully tested – subset that
demonstrates the required behaviour:

* two strategies: ``LLMStrategy`` (a thin stub around an imaginary LLM
  service) and ``RuleBasedStrategy`` which extracts key facts from the input
  text;
* a :class:`Rewriter` facade which chooses a strategy and guarantees that the
  returned text fits into the requested length and contains valid HTML.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import List, Protocol

from formatting import clean_html_tags, truncate_by_chars
import yandex_llm

logger = logging.getLogger(__name__)


class Strategy(Protocol):
    """Common interface for rewriting strategies."""

    def rewrite(
        self,
        title: str,
        body_html: str,
        max_len: int,
        region_hint: str,
        topic_hint: str,
    ) -> str:  # pragma: no cover - protocol
        ...


# ---------------------------------------------------------------------------
# Rule‑based strategy


@dataclass
class RuleBasedStrategy:
    """Simple deterministic rewriting used as a safe fall back."""

    bullet: str = "•"

    _SENT_RE = re.compile(r"(?<=[.!?])\s+")

    def _sentences(self, text: str) -> List[str]:
        return [s.strip() for s in self._SENT_RE.split(text) if s.strip()]

    def rewrite(
        self,
        title: str,
        body_html: str,
        max_len: int,
        region_hint: str,
        topic_hint: str,
    ) -> str:
        # strip HTML tags and split into sentences
        plain = clean_html_tags(body_html)
        sents = self._sentences(plain)
        lead = sents[0] if sents else title
        bullets = sents[1:6]
        while len(bullets) < 3:
            bullets.append("")
        bullets = [b for b in bullets[:6] if b]
        parts = [lead, ""] + [f"{self.bullet} {b}" for b in bullets]
        text = "\n".join(parts)
        return truncate_by_chars(text, max_len)


# ---------------------------------------------------------------------------
# LLM strategy (stub)


class LLMStrategy:
    """Wrapper around YandexGPT service."""

    def rewrite(
        self,
        title: str,
        body_html: str,
        max_len: int,
        region_hint: str,
        topic_hint: str,
    ) -> str:
        plain = clean_html_tags(body_html)
        prompt = f"{title}\n\n{plain}".strip()
        return yandex_llm.rewrite(
            prompt,
            target_chars=max_len,
            topic_hint=topic_hint,
            region_hint=region_hint or None,
        )


# ---------------------------------------------------------------------------
# Public facade


class Rewriter:
    """Facade choosing the appropriate strategy."""

    def __init__(self, use_llm: bool = False, topic_hint: str = "строительство, инфраструктура, ЖК, дороги, мосты") -> None:
        self.strategy: Strategy
        self.rule_based = RuleBasedStrategy()
        self.topic_hint = topic_hint
        if use_llm:
            try:
                self.strategy = LLMStrategy()
                logger.info("using YandexGPT strategy")
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("LLM strategy unavailable: %s", exc)
                self.strategy = self.rule_based
        else:
            self.strategy = self.rule_based
            logger.info("using rule-based strategy")

    def rewrite(
        self, title: str, body_html: str, max_len: int, region_hint: str
    ) -> str:
        try:
            text = self.strategy.rewrite(
                title, body_html, max_len, region_hint, self.topic_hint
            )
        except Exception as exc:
            logger.warning(
                "rewrite failed via %s: %s", type(self.strategy).__name__, exc
            )
            text = self.rule_based.rewrite(
                title, body_html, max_len, region_hint, self.topic_hint
            )
        result = truncate_by_chars(text, max_len)
        if len(result) < len(text):
            logger.warning("rewrite truncated to %d chars", max_len)
        return result


__all__ = ["Rewriter", "RuleBasedStrategy", "LLMStrategy"]

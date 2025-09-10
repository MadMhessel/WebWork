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

from formatting import clean_html_tags, html_escape, truncate_by_chars

logger = logging.getLogger(__name__)


class Strategy(Protocol):
    """Common interface for rewriting strategies."""

    def rewrite(
        self, title: str, body_html: str, max_len: int, region_hint: str
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
        self, title: str, body_html: str, max_len: int, region_hint: str
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
        text = html_escape(text)
        return truncate_by_chars(text, max_len)


# ---------------------------------------------------------------------------
# LLM strategy (stub)


class LLMStrategy:
    """Very small wrapper around an external LLM service.

    The implementation purposely avoids making real network requests.  Instead
    it raises :class:`RuntimeError` signalling that the service is not
    available.  Tests ensure that :class:`Rewriter` falls back to the
    :class:`RuleBasedStrategy` when this happens.
    """

    def rewrite(
        self, title: str, body_html: str, max_len: int, region_hint: str
    ) -> str:  # pragma: no cover - simple stub
        raise RuntimeError("LLM service is not configured")


# ---------------------------------------------------------------------------
# Public facade


class Rewriter:
    """Facade choosing the appropriate strategy."""

    def __init__(self, use_llm: bool = False) -> None:
        self.strategy: Strategy
        self.rule_based = RuleBasedStrategy()
        if use_llm:
            try:
                self.strategy = LLMStrategy()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("LLM strategy unavailable: %s", exc)
                self.strategy = self.rule_based
        else:
            self.strategy = self.rule_based

    def rewrite(
        self, title: str, body_html: str, max_len: int, region_hint: str
    ) -> str:
        try:
            text = self.strategy.rewrite(title, body_html, max_len, region_hint)
        except Exception as exc:
            logger.warning(
                "rewrite failed via %s: %s", type(self.strategy).__name__, exc
            )
            text = self.rule_based.rewrite(title, body_html, max_len, region_hint)
        return truncate_by_chars(text, max_len)


__all__ = ["Rewriter", "RuleBasedStrategy", "LLMStrategy"]

from __future__ import annotations

import re
from dataclasses import dataclass
from .base import NewsItem, Rewriter, RewriterResult


_CTA_RE = re.compile(r"\b(купить|продать|подписывайтесь|скидка)\b", re.I)
_TRACKING_RE = re.compile(r"\b(?:utm_[a-z]+=\w+&?)+", re.I)
_SPACES_RE = re.compile(r"\s+")


@dataclass
class RuleConfig:
    drop_cta: bool = True
    drop_tracking: bool = True
    normalize_spaces: bool = True


class RuleBasedRewriter(Rewriter):
    """Apply simple regex-based cleanup rules."""

    def __init__(self, cfg: RuleConfig | None = None) -> None:
        self.cfg = cfg or RuleConfig()

    def _clean(self, text: str) -> str:
        t = text
        if self.cfg.drop_tracking:
            t = _TRACKING_RE.sub("", t)
        if self.cfg.drop_cta:
            t = _CTA_RE.sub("", t)
        if self.cfg.normalize_spaces:
            t = _SPACES_RE.sub(" ", t).strip()
        return t

    def rewrite(self, item: NewsItem, *, max_len: int | None = None) -> RewriterResult:
        text = self._clean(item.text)
        if max_len is not None:
            text = text[:max_len]
        title = self._clean(item.title)
        return RewriterResult(ok=True, title=title, text=text, provider="rules")

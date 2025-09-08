from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from .base import NewsItem, Rewriter, RewriterResult


@dataclass
class LLMConfig:
    provider: str = ""
    model: str = ""
    temperature: float = 0.2


class LLMRewriter(Rewriter):
    """Very small adapter around an external LLM provider.

    For test purposes this implementation simply fails when provider
    is missing which triggers fallback to rule based rewriter.
    """

    def __init__(self, cfg: LLMConfig | None = None) -> None:
        self.cfg = cfg or LLMConfig()

    def rewrite(self, item: NewsItem, *, max_len: int | None = None) -> RewriterResult:
        if not self.cfg.provider:
            raise RuntimeError("no provider configured")
        text = item.text if max_len is None else item.text[:max_len]
        return RewriterResult(ok=True, title=item.title, text=text, provider="llm")

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List

from .base import NewsItem, RewriterResult
from .noop import NoopRewriter
from .llm import LLMRewriter, LLMConfig


@dataclass
class RewriterChainConfig:
    order: List[str] = field(default_factory=lambda: ["llm", "noop"])
    target_length: int = 600
    llm: LLMConfig = field(default_factory=LLMConfig)


def run_rewrite_with_fallbacks(item: NewsItem, cfg: RewriterChainConfig) -> RewriterResult:
    """Run rewriters in configured order until one succeeds."""
    last = RewriterResult(ok=True, title=item.title, text=item.text, provider="noop")
    for name in cfg.order:
        if name == "llm":
            rewriter = LLMRewriter(cfg.llm)
        elif name == "noop":
            rewriter = NoopRewriter()
        else:
            continue
        try:
            res = rewriter.rewrite(item, max_len=cfg.target_length)
            res.provider = name
            return res
        except Exception as exc:
            last = RewriterResult(
                ok=False,
                title=item.title,
                text=item.text,
                provider=name,
                reasons=[f"{name}: {exc}"] if str(exc) else [name],
            )
    return last

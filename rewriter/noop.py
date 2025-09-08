from __future__ import annotations

from .base import NewsItem, Rewriter, RewriterResult


class NoopRewriter(Rewriter):
    """Return the item unchanged."""

    def rewrite(self, item: NewsItem, *, max_len: int | None = None) -> RewriterResult:
        text = item.text if max_len is None else item.text[:max_len]
        return RewriterResult(
            ok=True,
            title=item.title,
            text=text,
            provider="noop",
            reasons=["noop"] if max_len and len(item.text) > len(text) else []
        )

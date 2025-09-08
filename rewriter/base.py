from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, List, Optional


@dataclass
class NewsItem:
    """Minimal representation of a news item used by rewriters."""
    id: str
    source: str
    url: str
    title: str
    text: str
    html: Optional[str] = None
    images: List[str] | None = None
    published_at: Optional[str] = None  # simplified for tests
    region_tags: List[str] = field(default_factory=list)
    topic_tags: List[str] = field(default_factory=list)


@dataclass
class RewriterResult:
    ok: bool
    title: str
    text: str
    provider: str
    reasons: List[str] = field(default_factory=list)


class Rewriter(Protocol):
    def rewrite(self, item: NewsItem, *, max_len: int | None = None) -> RewriterResult:
        ...

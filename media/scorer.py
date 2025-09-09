from __future__ import annotations

from typing import List, Optional
import re

# Keywords signalling low-quality images
BAD_KEYWORDS = {"logo", "sprite", "icon"}
_PLACEHOLDER_RE = re.compile(
    r"(no[-_]?image|placeholder|plug|zaglushka|stub|default|spacer|1x1)",
    re.I,
)


def score_url(url: str) -> int:
    """Heuristically score ``url`` to favour large non-placeholder images."""
    low = url.lower()
    if _PLACEHOLDER_RE.search(low):
        return -100
    score = 0
    if any(k in low for k in BAD_KEYWORDS):
        score -= 20
    m = re.search(r"(\d{2,4})x(\d{2,4})", low)
    if m:
        score += int(m.group(1)) + int(m.group(2))
    if "@2x" in low or "@3x" in low:
        score += 10
    return score


def pick_best(urls: List[str]) -> Optional[str]:
    best_url = None
    best_score = -999
    for u in urls:
        s = score_url(u)
        if s > best_score:
            best_score = s
            best_url = u
    return best_url

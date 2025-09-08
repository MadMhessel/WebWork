from __future__ import annotations

from typing import List, Optional


BAD_KEYWORDS = {"logo", "sprite", "icon", "advert"}


def score_url(url: str) -> int:
    low = url.lower()
    if any(k in low for k in BAD_KEYWORDS):
        return -10
    return 0


def pick_best(urls: List[str]) -> Optional[str]:
    best_url = None
    best_score = -999
    for u in urls:
        s = score_url(u)
        if s > best_score:
            best_score = s
            best_url = u
    return best_url

from __future__ import annotations

from typing import List, Optional
import re


BAD_KEYWORDS = {"logo", "sprite", "icon", "advert", "1x1", "pixel"}


def score_url(url: str) -> int:
    low = url.lower()
    score = 0
    if any(k in low for k in BAD_KEYWORDS):
        score -= 10
    if low.endswith(('.gif', '.webp')):
        score -= 5
    m = re.search(r'(\d+)x(\d+)', low)
    if m and (m.group(1) == '1' or m.group(2) == '1'):
        score -= 5
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

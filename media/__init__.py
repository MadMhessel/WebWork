from __future__ import annotations

from .extractor import extract_image_urls
from .scorer import pick_best


def select_best_image(item) -> str | None:
    """Return best image URL for item or None."""
    urls = extract_image_urls(item)
    return pick_best(urls)

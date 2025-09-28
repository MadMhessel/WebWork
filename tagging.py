import re
from pathlib import Path
from typing import Set, Tuple

import yaml

_RULES_CACHE: dict | None = None


def _load_rules() -> dict:
    global _RULES_CACHE
    if _RULES_CACHE is None:
        path = Path(__file__).resolve().parent / "tag_rules.yaml"
        with path.open("r", encoding="utf-8") as fh:
            _RULES_CACHE = yaml.safe_load(fh) or {}
    return _RULES_CACHE


def extract_tags(text: str) -> Tuple[Set[str], bool]:
    """Return set of tags and flag for global negative topics."""
    rules = _load_rules()
    t = text or ""
    tags: Set[str] = set()

    # geo tags
    geo = rules.get("geo", {}).get("city_aliases", {})
    for _, data in geo.items():
        pats = data.get("patterns", [])
        for p in pats:
            if re.search(p, t, flags=re.I | re.U):
                tags.update(data.get("tags", []))
                break

    # category tags
    categories = rules.get("categories", [])
    for cat in categories:
        pos = any(re.search(p, t, flags=re.I | re.U) for p in cat.get("positive", []))
        neg = any(re.search(p, t, flags=re.I | re.U) for p in cat.get("negative", []))
        if pos and not neg:
            tags.update(cat.get("post_tags", []))

    neg_topics = any(
        re.search(p, t, flags=re.I | re.U)
        for p in rules.get("negative_topics_global", [])
    )
    return tags, neg_topics

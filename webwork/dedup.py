"""Helpers for canonical URL normalisation and duplicate detection."""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Iterable, Optional
from urllib.parse import parse_qsl, urlsplit, urlunsplit, urlencode

from . import dedup_config

logger = logging.getLogger(__name__)


def canonical_url(url: Optional[str]) -> str:
    """Return a canonicalised version of ``url`` suitable for dedup keys."""

    if not url:
        return ""
    parsed = urlsplit(url)
    clean_path = parsed.path.rstrip("/")
    query_params = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    clean_query = urlencode(query_params, doseq=True)
    return urlunsplit((parsed.scheme, parsed.netloc, clean_path, clean_query, ""))


_TITLE_REPLACEMENTS = re.compile(r"\((фото|видео)\)", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")


def title_norm(title: Optional[str]) -> str:
    """Normalise ``title`` to improve duplicate detection stability."""

    if not title:
        return ""
    lowered = unicodedata.normalize("NFKD", title).lower()
    lowered = lowered.replace("ё", "е")
    lowered = _TITLE_REPLACEMENTS.sub("", lowered)
    lowered = re.sub(r"[^0-9a-zа-я ]+", " ", lowered)
    lowered = _WHITESPACE_RE.sub(" ", lowered)
    return lowered.strip()


def dedup_key(url: Optional[str], title: Optional[str], *, algorithm: str = "sha256") -> str:
    """Compute a stable hash for ``url``/``title`` combination."""

    base = canonical_url(url) or title_norm(title)
    if not base:
        return ""
    algo = algorithm.lower()
    data = base.encode("utf-8")
    if algo == "sha1":
        return hashlib.sha1(data, usedforsecurity=False).hexdigest()
    return hashlib.sha256(data).hexdigest()


def near_duplicate(
    title: Optional[str],
    candidates: Iterable[str],
    *,
    threshold: Optional[float] = None,
) -> Optional[tuple[str, float]]:
    """Return the most similar candidate if "near duplicates" are enabled."""

    cfg = dedup_config()
    if not cfg.near_duplicates_enabled:
        return None
    base = title_norm(title)
    if not base:
        return None
    limit = threshold if threshold is not None else cfg.near_duplicate_threshold
    best_score = 0.0
    best_candidate: Optional[str] = None
    for other in candidates:
        other_norm = title_norm(other)
        if not other_norm or other_norm == base:
            continue
        score = SequenceMatcher(None, base, other_norm).ratio()
        if score > best_score and score >= limit:
            best_score = score
            best_candidate = other
    if best_candidate is None:
        return None
    logger.info("Near duplicate detected: %.3f against '%s'", best_score, best_candidate[:140])
    return best_candidate, best_score

from __future__ import annotations

import logging
import re
from typing import Any, Dict

from autorewrite.rewriter import rewrite_post

log = logging.getLogger(__name__)

_TAGS_RE = re.compile(r"<[^>]+>")


def _get_cfg_attr(cfg, name: str, default):
    try:
        return getattr(cfg, name)
    except Exception:
        return default


def _strip_tags(text: str) -> str:
    return _TAGS_RE.sub(" ", text or "")


def _normalize_ws(text: str) -> str:
    t = (text or "").replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\s+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _limit_length(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    cut = re.sub(r"\s+\S*$", "", cut).strip()
    return cut


def _rewrite(clean: str, cfg) -> Dict[str, Any]:
    tg_limit = int(_get_cfg_attr(cfg, "TELEGRAM_MESSAGE_LIMIT", 4096))
    rewrite_cap = int(_get_cfg_attr(cfg, "REWRITE_MAX_CHARS", min(900, tg_limit - 500)))
    desired_len = max(200, min(rewrite_cap, tg_limit - 200))
    return rewrite_post(text=clean, desired_len=desired_len)


def rewrite_text(original: str, cfg) -> str:
    """Rewrite raw text returning only rewritten body."""
    try:
        if not original:
            return ""
        if not bool(_get_cfg_attr(cfg, "ENABLE_REWRITE", True)):
            return _normalize_ws(_strip_tags(original))
        clean = _normalize_ws(_strip_tags(original))
        res = _rewrite(clean, cfg)
        return res.get("text", "")
    except Exception as ex:  # pragma: no cover - defensive
        log.exception("\u041e\u0448\u0438\u0431\u043a\u0430 \u0440\u0435\u0440\u0430\u0439\u0442\u0430, \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0435\u043c \u0431\u0435\u0440\u0435\u0436\u043d\u043e\u0435 \u0441\u043e\u043a\u0440\u0430\u0449\u0435\u043d\u0438\u0435: %s", ex)
        safe = _normalize_ws(_strip_tags(original))
        tg_limit = int(_get_cfg_attr(cfg, "TELEGRAM_MESSAGE_LIMIT", 4096))
        return _limit_length(safe, max(200, tg_limit - 200))


def maybe_rewrite_item(item: dict, cfg) -> dict:
    """Rewrite news item dict in-place-compatible way.

    Returns a shallow copy of ``item`` with rewritten ``title`` and ``content``
    when rewriting is enabled. Similarity metrics and warnings (if any) are
    stored under ``rewrite_similarity`` and ``rewrite_warnings`` keys.
    """
    try:
        out = dict(item)
        if not bool(_get_cfg_attr(cfg, "ENABLE_REWRITE", True)):
            out["content"] = _normalize_ws(_strip_tags(out.get("content", "") or ""))
            return out
        clean = _normalize_ws(_strip_tags(out.get("content", "") or ""))
        res = _rewrite(clean, cfg)
        out["content"] = res.get("text", "")
        if res.get("title"):
            out["title"] = res["title"]
        if res.get("similarity"):
            out["rewrite_similarity"] = res["similarity"]
        if res.get("warnings"):
            out["rewrite_warnings"] = res["warnings"]
        return out
    except Exception:  # pragma: no cover - defensive
        return item

"""Thin wrapper around :mod:`rewriter_module` used by :mod:`main`.

The original project historically exposed helper functions ``rewrite_text`` and
``maybe_rewrite_item``.  The newly introduced :class:`~rewriter_module.Rewriter`
implements the actual logic.  To keep the rest of the code base unchanged we
provide a small compatibility layer that wires the new class into the existing
functions.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict

from formatting import clean_html_tags
from rewriter_module import Rewriter

log = logging.getLogger(__name__)

_FIGURE_RE = re.compile(r"<figure[^>]*>.*?</figure>", re.I | re.S)

_rewriter: Rewriter | None = None


def _instance(cfg) -> Rewriter:
    """Lazily create a :class:`Rewriter` instance based on config."""

    global _rewriter
    if _rewriter is None:
        creds_ok = bool(getattr(cfg, "YANDEX_API_KEY", "") or getattr(cfg, "YANDEX_IAM_TOKEN", ""))
        use_llm = bool(getattr(cfg, "YANDEX_REWRITE_ENABLED", False) and creds_ok)
        topic_hint = "строительство, инфраструктура, ЖК, дороги, мосты"
        _rewriter = Rewriter(use_llm=use_llm, topic_hint=topic_hint)
    return _rewriter


def rewrite_text(original: str, cfg) -> str:
    """Rewrite ``original`` body HTML using the new :class:`Rewriter`.

    Falls back to returning a cleaned version of the input when rewriting is
    disabled via configuration or when any unexpected error occurs.
    """

    if not original:
        return ""
    try:
        if not bool(getattr(cfg, "ENABLE_REWRITE", True)):
            return clean_html_tags(_FIGURE_RE.sub(" ", original))
        max_len = int(
            getattr(cfg, "REWRITE_MAX_CHARS", getattr(cfg, "MAX_POST_LEN", 4000))
        )
        region = getattr(
            cfg, "REGION_HINT", "Нижегородская область, Нижний Новгород"
        )
        return _instance(cfg).rewrite("", original, max_len, region)
    except Exception as exc:  # pragma: no cover - defensive
        log.exception(
            "\u041e\u0448\u0438\u0431\u043a\u0430 \u0440\u0435\u0440\u0430\u0439\u0442\u0430: %s",
            exc,
        )
        return clean_html_tags(_FIGURE_RE.sub(" ", original))


def maybe_rewrite_item(item: Dict[str, Any], cfg) -> Dict[str, Any]:
    """Rewrite fields of ``item`` in a backwards compatible manner."""

    out = dict(item)
    try:
        if not bool(getattr(cfg, "ENABLE_REWRITE", True)):
            out["content"] = clean_html_tags(
                _FIGURE_RE.sub(" ", out.get("content", "") or "")
            )
            return out

        max_len = int(
            getattr(cfg, "REWRITE_MAX_CHARS", getattr(cfg, "MAX_POST_LEN", 4000))
        )
        region = getattr(
            cfg, "REGION_HINT", "Нижегородская область, Нижний Новгород"
        )
        title = out.get("title", "")
        body = out.get("content", "")
        out["content"] = _instance(cfg).rewrite(title, body, max_len, region)
        return out
    except Exception as exc:  # pragma: no cover - defensive
        log.exception(
            "\u041e\u0448\u0438\u0431\u043a\u0430 \u0440\u0435\u0440\u0430\u0439\u0442\u0430: %s",
            exc,
        )
        return out


__all__ = ["rewrite_text", "maybe_rewrite_item"]

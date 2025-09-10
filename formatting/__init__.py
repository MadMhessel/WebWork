"""Utility helpers for preparing text for Telegram HTML mode.

The real project contains a rather involved formatting module.  For the
purposes of the tests in this kata we only need a tiny subset of that
behaviour: escaping unsafe characters, stripping unsupported tags and
truncating text by character count.  The functions implemented here are
intentionally small but well documented and type annotated which makes them
easy to unit test and reuse.
"""

from __future__ import annotations

from html import escape as _escape
import re

_ALLOWED_TAGS = {"b", "i", "u", "s", "a", "code"}
_TAG_RE = re.compile(r"<(/?)([a-zA-Z0-9]+)(?:\s[^>]*)?>")


def html_escape(text: str) -> str:
    """Escape special characters for safe usage in HTML.

    Telegram expects valid HTML in ``parse_mode=HTML`` posts.  Any special
    characters must therefore be escaped.  Python's :func:`html.escape` takes
    care of ``&``, ``<`` and ``>``, but Telegram is also picky about quotes and
    slashes so we handle those as well.
    """

    text = _escape(text, quote=True)
    return text.replace("/", "&#x2F;")


def truncate_by_chars(text: str, max_len: int) -> str:
    """Return ``text`` truncated to ``max_len`` characters.

    The function is deliberately conservative – it simply slices the string and
    ensures no lingering open HTML tags remain by stripping them afterwards.
    """

    if len(text) <= max_len:
        return text
    truncated = text[:max_len]
    return clean_html_tags(truncated)


def clean_html_tags(text: str) -> str:
    """Remove all HTML tags except for the small safe subset.

    Any tag not present in :data:`_ALLOWED_TAGS` is stripped entirely.  Closing
    tags without their opening counterparts are also removed which prevents the
    dreaded ``Unexpected end tag`` errors from Telegram.
    """

    def _replace(match: re.Match[str]) -> str:
        name = match.group(2).lower()
        if name in _ALLOWED_TAGS:
            # keep the tag as-is
            return match.group(0)
        return ""

    cleaned = _TAG_RE.sub(_replace, text)
    # remove lonely closing tags for allowed tags
    for tag in _ALLOWED_TAGS:
        cleaned = re.sub(
            rf"</{tag}>",
            lambda m: "" if f"<{tag}" not in cleaned else m.group(0),
            cleaned,
        )
    return cleaned


__all__ = ["html_escape", "truncate_by_chars", "clean_html_tags"]

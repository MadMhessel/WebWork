import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from formatting.telegram import escape_markdown_v2, sanitize_markdown_v2, split_to_telegram_chunks


def test_escape_markdown_v2():
    s = "[]()_*>#-+.!|{}"
    esc = escape_markdown_v2(s)
    for ch in s:
        assert f"\\{ch}" in esc


def test_markdownv2_truncation_is_safe():
    text = "a" * 49 + "\\"
    parts = split_to_telegram_chunks(text, limit=50)
    assert parts[0] == "a" * 49
    for part in parts:
        assert not part.endswith("\\")
        assert sanitize_markdown_v2(part) == part

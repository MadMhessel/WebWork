import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from formatting.telegram import escape_markdown_v2


def test_escape_markdown_v2():
    s = "[]()_*>#-+.!|{}"
    esc = escape_markdown_v2(s)
    for ch in s:
        assert f"\\{ch}" in esc

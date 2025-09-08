import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from rewriter.base import NewsItem
from media.telegram import build_caption, build_text_messages


def test_caption_truncated_to_limit():
    text = "a" * 2000
    item = NewsItem(id="1", source="s", url="https://example.com", title="t", text=text)
    caption = build_caption(item, item.url, limit=1024)
    assert len(caption) <= 1024


def test_text_split_into_chunks():
    text = "word " * 1000  # ~5000 chars
    item = NewsItem(id="1", source="s", url="u", title="t", text=text)
    parts = build_text_messages(item, limit=1000)
    assert len(parts) > 1
    assert all(len(p) <= 1000 for p in parts)

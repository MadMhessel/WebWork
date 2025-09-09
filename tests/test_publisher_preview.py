import sys, pathlib

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))
from WebWork import publisher, config


def test_compose_preview_limits_markdown():
    title = "[title]" * 50
    body = "_" * 5000
    url = "https://example.com"
    caption, long_text = publisher.compose_preview(title, body, url, "MarkdownV2")
    assert len(caption) <= config.CAPTION_LIMIT
    if long_text:
        assert len(long_text) <= config.TELEGRAM_MESSAGE_LIMIT
        assert not long_text.endswith("\\")
    assert not caption.endswith("\\")

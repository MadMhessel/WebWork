from WebWork import config, publisher


def test_compose_preview_limits_markdown(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_PARSE_MODE", "MarkdownV2")
    title = "[title]" * 50
    body = "_" * 5000
    url = "https://example.com"
    caption, long_text = publisher.compose_preview(
        title, body, url, config.TELEGRAM_PARSE_MODE
    )
    assert len(caption) <= config.CAPTION_LIMIT
    if long_text:
        assert len(long_text) <= config.TELEGRAM_MESSAGE_LIMIT
        assert not long_text.endswith("\\")
    assert not caption.endswith("\\")

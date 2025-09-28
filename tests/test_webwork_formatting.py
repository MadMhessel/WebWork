import pytest

from webwork.utils.formatting import chunk_text, escape_markdown_v2, safe_format
from webwork.dedup import canonical_url, dedup_key


@pytest.mark.parametrize(
    "source, expected",
    [
        ("plain", "plain"),
        ("_bold_", r"\_bold\_"),
        ("special!chars", r"special\!chars"),
        ("mix_*[]()~`>#+-=|{}.!", r"mix\_\*\[\]\(\)\~\`\>\#\+\-\=\|\{\}\.\!"),
    ],
)
def test_escape_markdown_v2(source: str, expected: str) -> None:
    assert escape_markdown_v2(source) == expected


def test_safe_format_markdown_v2() -> None:
    text = "Escape _and_ *asterisks*"
    assert safe_format(text, "MarkdownV2") == "Escape \\_and\\_ \\*asterisks\\*"


def test_chunk_text_respects_limit() -> None:
    text = "paragraph one\nparagraph two\nparagraph three"
    chunks = chunk_text(text, limit=20)
    assert all(len(chunk) <= 20 for chunk in chunks)
    assert "paragraph one" in chunks[0]
    assert "three" in chunks[-1]


def test_chunk_text_long_paragraph() -> None:
    text = "a" * 15 + "b" * 10
    chunks = chunk_text(text, limit=16)
    assert all(len(chunk) <= 16 for chunk in chunks)
    assert "".join(chunks) == text


def test_canonical_url_strips_utm_and_trailing_slash() -> None:
    url = "https://example.com/path/?utm_source=news&utm_medium=rss&id=42"
    assert canonical_url(url) == "https://example.com/path?id=42"


def test_dedup_key_consistent_for_equivalent_urls() -> None:
    first = dedup_key("https://example.com/post?utm_campaign=test", None)
    second = dedup_key("https://example.com/post/", None)
    assert first == second


def test_dedup_key_uses_title_when_url_missing() -> None:
    first = dedup_key(None, "Заголовок (фото)")
    second = dedup_key(None, "заголовок (ФОТО)")
    assert first == second

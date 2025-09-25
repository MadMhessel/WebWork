import re

from WebWork import publisher


def _check_balanced(part: str) -> None:
    for tag in ("b", "i", "u", "s", "a", "code", "pre", "blockquote"):
        start = len(re.findall(rf"<{tag}(?:\s[^>]*)?>", part, flags=re.I))
        end = len(re.findall(rf"</{tag}>", part, flags=re.I))
        assert start == end


def test_split_balances_complex_tags():
    html = (
        "<p><b>Важное сообщение</b> — <i>проект</i></p>"
        "<blockquote>"
        "<p>Описание объекта <a href='https://example.com/path?a=1&b=2'>ссылка</a></p>"
        "<pre>&lt;code&gt;Блок&lt;/code&gt;</pre>"
        "</blockquote>"
        "<p>Заключение с дополнительными <u>данными</u></p>"
    )
    parts = publisher.split_html_message(html, limit=120)
    assert len(parts) >= 2
    for part in parts:
        _check_balanced(part)
        assert "<blockquote" not in part or "</blockquote>" in part
        assert "<pre>" not in part or "</pre>" in part


def test_split_handles_entities_and_links():
    html = (
        "<p>Начало &amp; подробности про <a href='https://example.com/long/path?query=1&ref=promo'>"
        "длинную ссылку</a> внутри текста.</p>"
        "<p>Дополнение &amp; данные для второго абзаца, чтобы вынудить разбиение.</p>"
    )
    parts = publisher.split_html_message(html, limit=150)
    assert len(parts) == 2
    assert any("&amp;" in part for part in parts)
    for part in parts[:-1]:
        assert not part.endswith("&")
    assert "https://example.com/long/path?query=1&ref=promo" in "".join(parts)
    for part in parts:
        _check_balanced(part)

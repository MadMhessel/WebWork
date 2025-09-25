from WebWork import publisher


def test_split_html_message_balances_inline_tags():
    html = (
        "<p><b>Важная</b> новость про <a href='https://example.com'>объект</a></p>"
        "<p><i>Дополнение &amp; детали</i></p>"
        "<p><code>Код &lt;не&gt; должен</code> прерываться</p>"
    )
    parts = publisher.split_html_message(html, limit=80)
    assert len(parts) >= 2
    for part in parts:
        assert part.count("<b>") == part.count("</b>")
        assert part.count("<i>") == part.count("</i>")
        assert part.count("<a") == part.count("</a>")
        assert part.count("<code>") == part.count("</code>")
        assert not any(tag in part for tag in ["<p", "</p>", "<div", "</div>"])
    assert any("&amp;" in part for part in parts)


def test_split_html_message_preserves_entities_and_min_size():
    text = "".join(f"<p>Блок {i} &amp; данные</p>" for i in range(12))
    parts = publisher.split_html_message(text, limit=120)
    assert len(parts) > 1
    limit = 120
    min_len = getattr(publisher, "_MIN_CHUNK_LENGTH", 160)
    effective_min = min(min_len, limit)
    threshold = int(effective_min * 0.75)
    for idx, part in enumerate(parts[:-1]):
        assert len(part) >= threshold or part.endswith("</blockquote>")
    assert "&amp;" in "".join(parts)
    combined = "".join(parts)
    assert combined.count("Блок 0") == 1 and combined.count("Блок 11") == 1


def test_prepare_publication_chunks_adds_prefix_and_header():
    item = {
        "title": "Заголовок",
        "content": "".join(f"<p>Блок {i}</p>" for i in range(20)),
        "url": "https://example.com",
        "rubric": "objects",
        "source_domain": "example.com",
    }
    chunks = publisher._prepare_publication_chunks(item, 150)  # pylint: disable=protected-access
    assert len(chunks) > 1
    assert chunks[0].startswith("(1/")
    assert "Рубрика: <b>objects</b>" in chunks[0]

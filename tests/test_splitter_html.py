from WebWork import publisher


def test_split_html_message_preserves_tags():
    html = "".join(f"<p>Абзац {i}</p>" for i in range(20))
    parts = publisher.split_html_message(html, limit=80)
    assert len(parts) > 1
    for part in parts:
        assert part.count("<p") == part.count("</p>")
        assert len(part) <= 80 or part.endswith("</p>")
    combined = "".join(parts)
    assert "Абзац 0" in combined and "Абзац 19" in combined


def test_prepare_publication_chunks_adds_prefix():
    item = {
        "title": "Заголовок",
        "content": "".join(f"<p>Блок {i}</p>" for i in range(15)),
        "url": "https://example.com",
        "rubric": "objects",
        "source_domain": "example.com",
    }
    chunks = publisher._prepare_publication_chunks(item, 120)  # pylint: disable=protected-access
    assert len(chunks) > 1
    assert chunks[0].startswith("(1/")
    assert chunks[1].startswith("(2/")

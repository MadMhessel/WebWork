from formatting import clean_html_tags, html_escape, truncate_by_chars


def test_html_escape_and_truncate():
    text = "<b>5 & 6</b>"
    escaped = html_escape(text)
    assert "&lt;b&gt;5 &amp; 6&lt;&#x2F;b&gt;" == escaped
    assert truncate_by_chars(escaped, 5) == "&lt;b"


def test_clean_html_tags():
    src = "<p>hello <script>alert(1)</script><b>world</b></p>"
    cleaned = clean_html_tags(src)
    assert "<script>" not in cleaned
    assert "<b>world</b>" in cleaned

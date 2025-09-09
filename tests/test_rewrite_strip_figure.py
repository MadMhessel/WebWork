import types

from WebWork import rewrite, images


def test_rewrite_removes_figure_block():
    html = '<p>a</p><figure><img alt="b" src="http://e/img.jpg"/><figcaption>b</figcaption></figure><p>c</p>'
    cfg = types.SimpleNamespace(ENABLE_REWRITE=False)
    cleaned = rewrite.rewrite_text(html, cfg)
    assert cleaned == 'a c'


def test_image_candidates_gone_after_rewrite():
    html = '<figure><img src="http://example.com/a.jpg"/></figure>'
    item = {'url': 'http://example.com', 'content': html}
    assert images.extract_candidates(item)
    rewritten = rewrite.rewrite_text(html, types.SimpleNamespace(ENABLE_REWRITE=False))
    assert images.extract_candidates({'url': 'http://example.com', 'content': rewritten}) == []

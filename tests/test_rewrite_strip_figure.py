import types

from WebWork import rewrite


def test_rewrite_removes_figure_block():
    html = '<p>a</p><figure><img alt="b" src="http://e/img.jpg"/><figcaption>b</figcaption></figure><p>c</p>'
    cfg = types.SimpleNamespace(ENABLE_REWRITE=False)
    cleaned = rewrite.rewrite_text(html, cfg)
    assert cleaned == 'a c'



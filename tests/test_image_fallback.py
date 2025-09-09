import sys
import pathlib

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))
from WebWork import images


def test_select_image_prefers_meta_tags():
    html = '<meta property="og:image" content="/og.jpg"><img src="/img.jpg">'
    item = {"title": "t", "url": "http://site/page", "content": html}
    url = images.select_image(item)
    assert url == "http://site/og.jpg"


def test_select_image_returns_none_when_none_found():
    item = {"title": "t", "content": "no images"}
    url = images.select_image(item)
    assert url is None


def test_resolve_image_returns_empty_when_invalid(monkeypatch):
    monkeypatch.setattr(images, "probe_image", lambda url, referer=None: None)
    item = {"title": "t", "content": '<img src="http://bad/img.png">'}
    info = images.resolve_image(item)
    assert info == {}

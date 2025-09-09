import sys
import pathlib

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))
from WebWork import images, config


def test_select_image_prefers_meta_tags():
    html = '<meta property="og:image" content="/og.jpg"><img src="/img.jpg">'
    item = {"title": "t", "url": "http://site/page", "content": html}
    url = images.select_image(item)
    assert url == "http://site/og.jpg"


def test_no_fallback_when_none_found(monkeypatch):
    monkeypatch.setattr(config, "FALLBACK_IMAGE_URL", "http://fallback/img.png")
    item = {"title": "t", "content": "no images"}
    url = images.select_image(item)
    assert url is None


def test_resolve_image_returns_empty_when_invalid(monkeypatch):
    monkeypatch.setattr(images, "probe_image", lambda url, referer=None: None)
    monkeypatch.setattr(config, "FALLBACK_IMAGE_URL", "http://fallback/img.png")
    item = {"title": "t", "content": '<img src="http://bad/img.png">'}
    info = images.resolve_image(item)
    assert info == {}

import sys
import pathlib

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))
from WebWork import images


def test_select_image_prefers_meta_tags(monkeypatch):
    def fake_probe(url, referer=None):
        if "og.jpg" in url:
            return ("h1", 1000, 1000)
        return ("h2", 100, 100)

    monkeypatch.setattr(images, "probe_image", fake_probe)
    html = '<meta property="og:image" content="/og.jpg"><img src="/img.jpg">'
    item = {"title": "t", "url": "http://site/page", "content": html}
    url = images.select_image(item)
    assert url == "http://site/og.jpg"


def test_select_image_returns_fallback_when_none_found(monkeypatch):
    monkeypatch.setattr(images, "FALLBACK_IMAGE_URL", "http://fallback/pic.jpg")
    monkeypatch.setattr(images, "ATTACH_IMAGES", True)
    monkeypatch.setattr(images, "ALLOW_PLACEHOLDER", True)
    monkeypatch.setattr(images, "probe_image", lambda url, referer=None: None)
    item = {"title": "t", "content": "no images"}
    url = images.select_image(item)
    assert url == "http://fallback/pic.jpg"


def test_resolve_image_returns_fallback_when_invalid(monkeypatch):
    monkeypatch.setattr(images, "probe_image", lambda url, referer=None: None)
    monkeypatch.setattr(images, "FALLBACK_IMAGE_URL", "http://fallback/pic.jpg")
    monkeypatch.setattr(images, "ATTACH_IMAGES", True)
    monkeypatch.setattr(images, "ALLOW_PLACEHOLDER", True)
    item = {"title": "t", "content": '<img src="http://bad/img.png">'}
    info = images.resolve_image(item)
    assert info["image_url"] == "http://fallback/pic.jpg"

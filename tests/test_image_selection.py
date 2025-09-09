import sys
import pathlib

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))
from WebWork import images


def test_select_image_json_ld(monkeypatch):
    monkeypatch.setattr(images, "probe_image", lambda url, referer=None: ("h", 800, 600))
    item = {
        "title": "t",
        "content": '<script type="application/ld+json">{"image": "http://img/ld.png"}</script>'
    }
    url = images.select_image(item)
    assert url == "http://img/ld.png"


def test_select_image_returns_fallback_when_none_found(monkeypatch):
    monkeypatch.setattr(images, "probe_image", lambda url, referer=None: None)
    monkeypatch.setattr(images, "FALLBACK_IMAGE_URL", "http://fallback/pic.jpg")
    monkeypatch.setattr(images, "ATTACH_IMAGES", True)
    item = {"title": "t", "content": "no images"}
    url = images.select_image(item)
    assert url == "http://fallback/pic.jpg"


def test_resolve_image_returns_fallback_when_candidate_invalid(monkeypatch):
    monkeypatch.setattr(images, "probe_image", lambda url, referer=None: None)
    monkeypatch.setattr(images, "FALLBACK_IMAGE_URL", "http://fallback/pic.jpg")
    monkeypatch.setattr(images, "ATTACH_IMAGES", True)
    item = {"title": "t", "content": '<img src="http://bad/img.png">'}
    info = images.resolve_image(item)
    assert info["image_url"] == "http://fallback/pic.jpg"

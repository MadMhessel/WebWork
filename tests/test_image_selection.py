import sys
import pathlib

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))
from WebWork import images


def test_select_image_json_ld():
    item = {
        "title": "t",
        "content": '<script type="application/ld+json">{"image": "http://img/ld.png"}</script>'
    }
    url = images.select_image(item)
    assert url == "http://img/ld.png"


def test_select_image_returns_none_when_none_found():
    item = {"title": "t", "content": "no images"}
    url = images.select_image(item)
    assert url is None


def test_resolve_image_returns_empty_when_candidate_invalid(monkeypatch):
    # probe_image returns None for any URL to emulate validation failure
    monkeypatch.setattr(images, "probe_image", lambda url, referer=None: None)

    item = {"title": "t", "content": '<img src="http://bad/img.png">'}
    info = images.resolve_image(item)
    assert info == {}

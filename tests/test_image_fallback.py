import sys
import pathlib

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))
from WebWork import images, config


def test_select_image_json_ld(monkeypatch):
    item = {
        "title": "t",
        "content": '<script type="application/ld+json">{"image": "http://img/ld.png"}</script>'
    }
    url = images.select_image_with_fallback(item)
    assert url == "http://img/ld.png"


def test_select_image_fallback(monkeypatch):
    monkeypatch.setattr(config, "FALLBACK_IMAGE_URL", "http://fallback/img.png")
    item = {"title": "t", "content": "no images"}
    url = images.select_image_with_fallback(item)
    assert url == "http://fallback/img.png"


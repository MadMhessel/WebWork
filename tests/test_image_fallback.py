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


def test_fallback_image_is_used_when_none_found(monkeypatch):
    monkeypatch.setattr(config, "FALLBACK_IMAGE_URL", "http://fallback/img.png")
    item = {"title": "t", "content": "no images"}
    url = images.select_image_with_fallback(item)
    assert url == "http://fallback/img.png"


def test_resolve_image_uses_fallback_when_candidate_invalid(monkeypatch):
    monkeypatch.setattr(config, "FALLBACK_IMAGE_URL", "http://fallback/img.png")

    # probe_image returns None for any URL to emulate validation failure
    monkeypatch.setattr(images, "probe_image", lambda url, referer=None: None)

    item = {"title": "t", "content": '<img src="http://bad/img.png">'}
    info = images.resolve_image(item)
    assert info["image_url"] == "http://fallback/img.png"
    assert "tg_file_id" not in info


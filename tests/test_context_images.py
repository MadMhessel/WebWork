import pathlib
import sys
import json

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))
sys.path.append(str(ROOT / "WebWork"))
from WebWork import context_images, config, images  # type: ignore


def test_build_query_adds_region(monkeypatch):
    monkeypatch.setattr(config, "REGION_HINT", "Нижний Новгород")
    q = context_images.build_query({"title": "Мост"}, config)
    assert "Мост" in q and "Нижний Новгород" in q


def test_openverse_success(monkeypatch):
    sample = {
        "results": [
            {
                "url": "http://img/ov.jpg",
                "width": 800,
                "height": 600,
                "license": "cc-by",
                "creator": "John",
                "foreign_landing_url": "http://src",
            }
        ]
    }

    def fake_get(url, params=None, timeout=None):
        return json.dumps(sample)

    monkeypatch.setattr(context_images.net, "get_text", fake_get)
    monkeypatch.setattr(images, "download_image", lambda u: (b"img", "image/jpeg"))
    res = context_images.fetch_context_image({"title": "t"}, config)
    assert res["provider"] == "openverse"
    assert res["bytes"] == b"img"


def test_openverse_filters_license(monkeypatch):
    sample = {
        "results": [
            {
                "url": "http://img/ov.jpg",
                "width": 800,
                "height": 600,
                "license": "cc-by-nc",
            }
        ]
    }

    def fake_get(url, params=None, timeout=None):
        return json.dumps(sample)

    monkeypatch.setattr(context_images.net, "get_text", fake_get)
    monkeypatch.setattr(images, "download_image", lambda u: (b"img", "image/jpeg"))
    res = context_images.fetch_context_image({"title": "t"}, config)
    assert res == {}

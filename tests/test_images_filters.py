import sys
import pathlib

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))
from WebWork import images


def test_extract_candidates_filters():
    item = {
        "image_url": "http://mc.yandex.ru/counter.gif",
        "content": '<img src="data:image/png;base64,xxx">'
        '<img src="http://example.com/logo.svg">'
        '<img src="http://site/no-image.png">'
        '<img src="http://good.com/pic.jpg">',
    }
    cands = images.extract_candidates(item)
    urls = [c.url for c in cands]
    assert "http://good.com/pic.jpg" in urls
    assert all(u.endswith(".jpg") for u in urls)
    assert not any("yandex" in u or "no-image" in u for u in urls)

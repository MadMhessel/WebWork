import sys
import pathlib

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))
from WebWork import fetcher

class Dummy:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_entry_to_item_rss_single_image_key():
    entry = Dummy(link="https://e", id="1", title="t", content=[])
    item = fetcher._entry_to_item_rss("src", entry)
    assert item is not None
    assert list(item.keys()).count("image_url") == 1


def test_fetch_html_list_single_image_key(monkeypatch):
    html = '<html><body><article><a href="/a">t</a><img src="img.jpg"></article></body></html>'
    source = {"name": "S", "url": "http://test/", "type": "html_list"}
    monkeypatch.setattr(fetcher, "_requests_get", lambda url, timeout=None, retry=None: html)
    monkeypatch.setattr(fetcher, "_parse_html_article", lambda *a, **k: None)
    items = fetcher.fetch_html_list(source, limit=1)
    assert items
    item = items[0]
    assert list(item.keys()).count("image_url") == 1

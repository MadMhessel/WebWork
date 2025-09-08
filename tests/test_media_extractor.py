import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from rewriter.base import NewsItem
from media.extractor import extract_image_urls


def test_extract_from_html_meta_and_img_and_list():
    html = '''<html><head><meta property="og:image" content="http://site/og.jpg"><meta name="twitter:image" content="http://site/tw.jpg"></head><body><img src="http://site/body.jpg"></body></html>'''
    item = NewsItem(id="1", source="s", url="u", title="t", text="", html=html, images=["http://site/extra.jpg"])
    urls = extract_image_urls(item)
    assert urls == ["http://site/extra.jpg", "http://site/og.jpg", "http://site/tw.jpg", "http://site/body.jpg"]

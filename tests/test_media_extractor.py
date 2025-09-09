import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from rewriter.base import NewsItem
from media.extractor import extract_image_urls


def test_extract_priority_and_filters():
    html = '''<html><head>
    <meta property="og:image" content="/og.jpg">
    <meta property="og:image:secure_url" content="https://cdn/og-sec.jpg">
    <meta name="twitter:image" content="http://site/tw.jpg">
    <script type="application/ld+json">{"image": "ld.jpg", "thumbnailUrl": "/thumb.jpg"}</script>
    </head><body>
    <picture><source srcset="/img1.jpg 1x, /img2.jpg 2x"></picture>
    <img data-src="img3.jpg">
    <img src="http://site/no-image.png">
    </body></html>'''
    item = NewsItem(id="1", source="s", url="http://site/page", title="t", text="", html=html)
    urls = extract_image_urls(item)
    assert urls == [
        "http://site/og.jpg",
        "https://cdn/og-sec.jpg",
        "http://site/tw.jpg",
        "http://site/ld.jpg",
        "http://site/thumb.jpg",
        "http://site/img2.jpg",
        "http://site/img3.jpg",
    ]

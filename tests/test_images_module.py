import io
from PIL import Image

import images


def test_extract_candidates():
    html = (
        '<meta property="og:image" content="a.jpg">'
        '<meta name="twitter:image" content="b.jpg">'
        '<script type="application/ld+json">{"image": "c.jpg"}</script>'
        '<img src="d.jpg">'
    )
    item = {"url": "http://example.com/news", "content": html}
    cands = images.extract_candidates(item)
    urls = [c.url for c in cands[:4]]
    assert "http://example.com/a.jpg" in urls
    assert "http://example.com/b.jpg" in urls
    assert "http://example.com/c.jpg" in urls
    assert "http://example.com/d.jpg" in urls


def test_pick_and_download_webp(monkeypatch, tmp_path):
    img = Image.new("RGBA", (500, 500), (255, 0, 0, 128))
    buf = io.BytesIO()
    img.save(buf, format="WEBP")
    raw = buf.getvalue()

    def fake_download(url, referer=None):
        return raw, "image/webp"

    monkeypatch.setattr(images, "download_image", fake_download)
    info1 = images.pick_and_download(["http://example.com/a.webp"])
    info2 = images.pick_and_download(["http://example.com/a.webp"])
    assert info1["local_path"] == info2["local_path"]
    assert info1["phash"] == info2["phash"]

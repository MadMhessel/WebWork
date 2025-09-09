import base64
from types import SimpleNamespace
import sys
import pathlib

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))
from WebWork import images, db

PNG_DATA = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
)


class Resp:
    def __init__(self, content):
        self.status_code = 200
        self.headers = {
            "Content-Type": "image/png",
            "Content-Length": str(len(content)),
        }
        self.content = content

    def iter_content(self, n):
        yield self.content


def test_no_fake_tg_file_id_generated(monkeypatch):
    calls = {"head": 0, "get": 0}

    def fake_head(url, timeout, allow_redirects=True):
        calls["head"] += 1
        return Resp(PNG_DATA)

    def fake_get(url, timeout):
        calls["get"] += 1
        return Resp(PNG_DATA)

    monkeypatch.setattr(images, "HTTP_SESSION", SimpleNamespace(head=fake_head, get=fake_get))
    monkeypatch.setattr(images.config, "IMAGE_MIN_EDGE", 1)
    monkeypatch.setattr(images.config, "IMAGE_MIN_AREA", 1)
    monkeypatch.setattr(images.config, "MIN_IMAGE_BYTES", 0)

    class DummyImg:
        size = (1, 1)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(images, "Image", SimpleNamespace(open=lambda b: DummyImg()))

    conn = db.connect(":memory:")
    db.init_schema(conn)

    fid1, h1 = images.ensure_tg_file_id("http://e/img.png", conn)
    fid2, h2 = images.ensure_tg_file_id("http://e/img.png", conn)
    assert fid1 is None and fid2 is None
    assert h1 == h2
    assert calls["head"] == 1 and calls["get"] == 1

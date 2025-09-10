import sys
import pathlib
import sqlite3
import sys
from io import BytesIO

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))
sys.path.append(str(ROOT / "WebWork"))
from WebWork import publisher, db, moderator, config


def test_publish_from_queue_prefers_url_then_caches_file_id(monkeypatch):
    conn = db.connect(":memory:")
    db.init_schema(conn)
    conn.execute(
        "INSERT INTO moderation_queue(id,title,content,url,image_url,status) VALUES (1,'t','c','u','http://img',?)",
        (moderator.APPROVED,),
    )
    conn.commit()
    monkeypatch.setattr(config, "ATTACH_IMAGES", True)
    monkeypatch.setattr(config, "PREVIEW_MODE", "auto")
    monkeypatch.setattr(config, "CHANNEL_CHAT_ID", "200")

    called = {}

    def fake_send_photo(chat_id, photo, caption, parse_mode, mime=None):
        called["photo_type"] = type(photo).__name__
        return ("m1", "fid1")

    def fake_send_text(chat_id, text, parse_mode):
        return "m2"

    monkeypatch.setattr(publisher, "_send_photo", fake_send_photo)
    monkeypatch.setattr(publisher, "_send_text", fake_send_text)
    monkeypatch.setattr(publisher, "_download_image", lambda url, cfg=config: (BytesIO(b"img"), "image/jpeg"))

    mid = publisher.publish_from_queue(conn, 1, cfg=config)
    assert mid == "m1"
    assert called["photo_type"] == "BytesIO"
    row = conn.execute("SELECT tg_file_id FROM moderation_queue WHERE id=1").fetchone()
    assert row["tg_file_id"] == "fid1"
    assert db.get_cached_file_id(conn, "http://img") == "fid1"


def test_publisher_message_with_image_url_sends_photo(monkeypatch):
    conn = db.connect(":memory:")
    db.init_schema(conn)
    monkeypatch.setattr(publisher.db, "connect", lambda: conn)
    monkeypatch.setattr(config, "ATTACH_IMAGES", True)
    called = {}

    def fake_send_photo(chat_id, photo, caption, parse_mode, mime=None):
        called["photo_type"] = type(photo).__name__
        return ("m1", "fid2")

    def fake_send_text(chat_id, text, parse_mode):
        called["text"] = text
        return "m2"

    monkeypatch.setattr(publisher, "_send_photo", fake_send_photo)
    monkeypatch.setattr(publisher, "_send_text", fake_send_text)
    monkeypatch.setattr(publisher, "_download_image", lambda url, cfg=config: (BytesIO(b"img"), "image/jpeg"))

    ok = publisher.publish_message("100", "t", "b", "u", image_url="http://img2", cfg=config)
    assert ok is True
    assert called["photo_type"] == "BytesIO"
    assert db.get_cached_file_id(conn, "http://img2") == "fid2"


def test_publish_message_uses_bytes_when_provided(monkeypatch):
    conn = db.connect(":memory:")
    db.init_schema(conn)
    monkeypatch.setattr(publisher.db, "connect", lambda: conn)
    monkeypatch.setattr(config, "ATTACH_IMAGES", True)
    called = {}

    def fake_send_photo(chat_id, photo, caption, parse_mode, mime=None):
        called["photo_type"] = type(photo).__name__
        called["mime"] = mime
        return ("m3", "fid3")

    def fake_send_text(chat_id, text, parse_mode):
        called["text"] = text
        return "m4"

    monkeypatch.setattr(publisher, "_send_photo", fake_send_photo)
    monkeypatch.setattr(publisher, "_send_text", fake_send_text)

    ok = publisher.publish_message(
        "100",
        "t",
        "b",
        "u",
        image_url="http://img3",
        image_bytes=b"123",
        image_mime="image/jpeg",
        cfg=config,
    )
    assert ok is True
    assert called["photo_type"] == "BytesIO"
    assert called["mime"] == "image/jpeg"
    assert db.get_cached_file_id(conn, "http://img3") == "fid3"


def test_preview_text_only(monkeypatch):
    item = {"title": "t", "content": "c", "url": "u", "image_url": "http://img"}
    monkeypatch.setattr(config, "PREVIEW_MODE", "text_only")
    called = {}

    def fake_send_text(chat_id, text, parse_mode, reply_markup=None):
        called["text"] = text
        return "m"

    def fake_send_photo(*a, **kw):
        raise AssertionError("photo should not be sent")

    monkeypatch.setattr(publisher, "_send_text", fake_send_text)
    monkeypatch.setattr(publisher, "_send_photo", fake_send_photo)

    publisher.send_moderation_preview("chat", item, 1, cfg=config)
    assert "text" in called

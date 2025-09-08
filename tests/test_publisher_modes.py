import sys
import pathlib
import sqlite3

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))
from WebWork import publisher, db, moderator, config, images


def test_publish_from_queue_fallback(monkeypatch):
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

    def fake_send_photo(chat_id, photo, caption, parse_mode):
        called["photo"] = photo
        return ("m1", None)

    def fake_send_text(chat_id, text, parse_mode):
        return "m2"

    def fake_ensure(url, conn):
        called["ensure"] = url
        return ("fid1", "h1")

    monkeypatch.setattr(publisher, "_send_photo", fake_send_photo)
    monkeypatch.setattr(publisher, "_send_text", fake_send_text)
    monkeypatch.setattr(images, "ensure_tg_file_id", fake_ensure)

    mid = publisher.publish_from_queue(conn, 1, cfg=config)
    assert mid == "m1"
    assert called["photo"] == "fid1"
    row = conn.execute("SELECT tg_file_id FROM moderation_queue WHERE id=1").fetchone()
    assert row["tg_file_id"] == "fid1"


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

import sys
import pathlib
import sqlite3

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))
from WebWork import db, moderator, publisher, config


def test_queue_and_publish(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_MODERATION", True)
    monkeypatch.setattr(config, "REVIEW_CHAT_ID", "100")
    monkeypatch.setattr(config, "CHANNEL_CHAT_ID", "200")
    monkeypatch.setattr(config, "MODERATOR_IDS", {1})

    preview_calls = {}
    publish_calls = {}

    def fake_preview(chat_id, item, mod_id, cfg=config):
        preview_calls["chat"] = chat_id
        preview_calls["id"] = mod_id
        return "m1"

    def fake_publish(conn, mod_id, text_override=None, cfg=config):
        publish_calls["id"] = mod_id
        conn.execute("UPDATE moderation_queue SET status='PUBLISHED' WHERE id=?", (mod_id,))
        return "m2"

    monkeypatch.setattr(publisher, "send_moderation_preview", fake_preview)
    monkeypatch.setattr(publisher, "publish_from_queue", fake_publish)

    conn = db.connect(":memory:")
    db.init_schema(conn)

    item = {
        "source_id": "src",
        "source": "src",
        "url": "https://e/1",
        "guid": "g1",
        "title": "t",
        "content": "c",
        "summary": "s",
        "image_url": "",
    }

    mod_id = moderator.enqueue_item(item, conn)
    assert mod_id is not None
    moderator.send_preview(conn, mod_id)
    assert preview_calls == {"chat": "100", "id": mod_id}
    assert moderator.is_moderator(1)
    assert not moderator.is_moderator(2)
    moderator.approve(conn, mod_id, 1)
    assert publish_calls == {"id": mod_id}
    row = conn.execute("SELECT status FROM moderation_queue WHERE id=?", (mod_id,)).fetchone()
    assert row["status"] == moderator.PUBLISHED

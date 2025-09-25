import pathlib
import sys

import pytest

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))

from WebWork import bot_updates, config, db, moderator, publisher


def test_sender_chat_allowed(monkeypatch):
    monkeypatch.setattr(config, "MODERATOR_IDS", set())
    monkeypatch.setattr(config, "REVIEW_CHAT_ID", "-100")

    conn = db.connect(":memory:")
    db.init_schema(conn)

    queue_calls: list[tuple[int, int]] = []

    def fake_queue(conn_arg, chat_id, page):
        queue_calls.append((chat_id, page))

    monkeypatch.setattr(moderator, "cmd_queue", fake_queue)

    denied: list[tuple[str, str]] = []

    def fake_send(chat_id, text, cfg=config):
        denied.append((chat_id, text))

    monkeypatch.setattr(publisher, "send_message", fake_send)

    update = {
        "message": {
            "chat": {"id": -100},
            "sender_chat": {"id": -100},
            "text": "/queue",
        }
    }

    bot_updates._handle_update(conn, None, update)

    assert queue_calls == [(-100, 1)]
    assert denied == []


def test_sender_chat_denied(monkeypatch):
    monkeypatch.setattr(config, "MODERATOR_IDS", set())
    monkeypatch.setattr(config, "REVIEW_CHAT_ID", "-100")

    conn = db.connect(":memory:")
    db.init_schema(conn)

    def fail_queue(*args, **kwargs):  # pragma: no cover - guard against unexpected call
        pytest.fail("cmd_queue must not be called")

    monkeypatch.setattr(moderator, "cmd_queue", fail_queue)

    denied: list[tuple[str, str]] = []

    def fake_send(chat_id, text, cfg=config):
        denied.append((chat_id, text))

    monkeypatch.setattr(publisher, "send_message", fake_send)

    update = {
        "message": {
            "chat": {"id": -200},
            "sender_chat": {"id": -200},
            "text": "/queue",
        }
    }

    bot_updates._handle_update(conn, None, update)

    assert denied == [("-200", "Нет доступа")]

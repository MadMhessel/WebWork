import time

import sys
import pathlib

project_root = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(project_root))
sys.path.append(str(project_root.parent))
from WebWork import publisher, config


def test_send_moderation_preview_includes_header(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_PARSE_MODE", "HTML")

    calls = []

    def fake_send_text(chat_id, text, parse_mode, reply_to_message_id=None):
        calls.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_to": reply_to_message_id,
                "parse_mode": parse_mode,
            }
        )
        return f"msg{len(calls)}"

    monkeypatch.setattr(publisher, "_send_text", fake_send_text)
    monkeypatch.setattr(publisher, "_send_with_retry", lambda action, cfg: action())

    item = {
        "title": "Заголовок",
        "content": "Текст новости",
        "url": "https://example.com",
        "source": "Источник",
        "tags": ["тест", "нижний"],
        "reasons": {"region": True, "topic": False},
        "fetched_at": int(time.time()) - 300,
    }

    mid = publisher.send_moderation_preview("chat", item, 5, cfg=config)

    assert mid == "msg1"
    assert calls, "ожидался хотя бы один вызов отправки"
    first = calls[0]["text"]
    assert first.startswith("🗞")
    assert "#5" in first
    assert "Источник" in first
    assert "🏷️" in first
    assert "Фильтр" in first
    assert calls[0]["reply_to"] is None
    assert calls[0]["parse_mode"] == "HTML"

from types import SimpleNamespace
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from webwork.publisher import send_photo_with_caption, send_text
from webwork.utils.formatting import TG_CAPTION_LIMIT, TG_TEXT_LIMIT


class DummyApi:
    def __init__(self) -> None:
        self.sent_messages: list[tuple[str, str]] = []
        self.sent_photos: list[tuple[str, str]] = []

    def sendMessage(self, chat_id: str, text: str, parse_mode: str | None = None) -> SimpleNamespace:  # noqa: N802 - Telegram casing
        self.sent_messages.append((chat_id, text))
        return SimpleNamespace(message_id=len(self.sent_messages))

    def sendPhoto(
        self,
        chat_id: str,
        photo: str,
        caption: str | None = None,
        parse_mode: str | None = None,
    ) -> SimpleNamespace:  # noqa: N802 - Telegram casing
        self.sent_photos.append((chat_id, caption or ""))
        return SimpleNamespace(message_id=len(self.sent_photos))


def test_send_text_respects_telegram_limit() -> None:
    api = DummyApi()
    long_text = "A" * (TG_TEXT_LIMIT + 200)
    send_text(api, "@test", long_text)
    assert len(api.sent_messages) == 2
    for _, text in api.sent_messages:
        assert len(text) <= TG_TEXT_LIMIT


def test_send_photo_caption_and_tail() -> None:
    api = DummyApi()
    caption = "B" * (TG_CAPTION_LIMIT + 300)
    send_photo_with_caption(api, "@test", "file_id", caption)
    assert len(api.sent_photos) == 1
    first_caption = api.sent_photos[0][1]
    assert len(first_caption) <= TG_CAPTION_LIMIT
    assert len(api.sent_messages) >= 1
    for _, text in api.sent_messages:
        assert len(text) <= TG_TEXT_LIMIT

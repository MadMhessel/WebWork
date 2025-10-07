import pathlib
import sys
import types

import asyncio

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import telegram_fetcher


def test_fetch_mtproto_async_requires_session_file(monkeypatch, tmp_path):
    missing_session = tmp_path / "missing.session"

    class DummyClient:
        def __init__(self, filename: str):
            self.session = types.SimpleNamespace(filename=filename)

        async def __aenter__(self):  # pragma: no cover - should not be called
            raise AssertionError("client should not be entered when session missing")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(telegram_fetcher, "get_mtproto_client", lambda *a, **k: DummyClient(str(missing_session)))
    monkeypatch.setattr(telegram_fetcher.config, "TELETHON_API_ID", 12345)
    monkeypatch.setattr(telegram_fetcher.config, "TELETHON_API_HASH", "hash")

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(
            telegram_fetcher._fetch_mtproto_async(
                ["example"], 5, options=telegram_fetcher.FetchOptions()
            )
        )

    assert str(missing_session) in str(exc_info.value)

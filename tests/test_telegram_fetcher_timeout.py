import pathlib
import sys
import threading
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import telegram_fetcher


def test_fetch_from_telegram_timeout_returns_control(monkeypatch):
    call_started = threading.Event()
    release_worker = threading.Event()

    def fake_fetch_sync(mode, links_file, limit, opts):
        call_started.set()
        release_worker.wait(timeout=30)
        return []

    monkeypatch.setattr(telegram_fetcher, "_fetch_from_telegram_sync", fake_fetch_sync)

    start = time.monotonic()
    elapsed = None
    try:
        with pytest.raises(telegram_fetcher.TelegramFetchTimeoutError):
            telegram_fetcher.fetch_from_telegram(
                "mtproto",
                "dummy_links.txt",
                5,
                options=telegram_fetcher.FetchOptions(timeout_seconds=1.0),
                timeout=1.0,
            )
    finally:
        elapsed = time.monotonic() - start
        release_worker.set()
    assert call_started.wait(timeout=1.0)
    assert elapsed is not None and elapsed < 5.0


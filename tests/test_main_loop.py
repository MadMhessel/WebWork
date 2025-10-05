import logging
import sqlite3
import sys
import types

import main
import config


def test_run_once_skips_mtproto_when_credentials_missing(monkeypatch, caplog):
    conn = sqlite3.connect(":memory:")

    monkeypatch.setattr(config, "RAW_STREAM_ENABLED", False)
    monkeypatch.setattr(config, "TELEGRAM_AUTO_FETCH", True)
    monkeypatch.setattr(config, "TELEGRAM_MODE", "mtproto")
    monkeypatch.setattr(config, "TELEGRAM_LINKS_FILE", "dummy_links.txt")
    monkeypatch.setattr(config, "TELEGRAM_FETCH_LIMIT", 5)
    monkeypatch.setattr(config, "TELETHON_API_ID", 0)
    monkeypatch.setattr(config, "TELETHON_API_HASH", "")
    monkeypatch.setattr(config, "ITEM_RETENTION_DAYS", 0)
    monkeypatch.setattr(config, "DEDUP_RETENTION_DAYS", 0)
    monkeypatch.setattr(config, "SOURCES_BY_NAME", {})
    monkeypatch.setattr(config, "SOURCES_BY_DOMAIN_ALL", {})

    fake_fetch_called = False

    def fake_fetch(*args, **kwargs):  # pragma: no cover - defensive
        nonlocal fake_fetch_called
        fake_fetch_called = True
        raise AssertionError("fetch_from_telegram should not be called")

    fake_module = types.SimpleNamespace(fetch_from_telegram=fake_fetch)
    monkeypatch.setitem(sys.modules, "telegram_fetcher", fake_module)

    caplog.set_level(logging.WARNING)

    result = main.run_once(conn, raw_mode="skip")

    assert result == (0, 0, 0, 0, 0, 0, 0, 0)
    assert not fake_fetch_called
    assert any(
        "TELEGRAM_MODE=mtproto" in record.message for record in caplog.records
    )

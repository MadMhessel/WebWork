import sqlite3
import sys
import pathlib
import time

# add repo parent to sys.path to import package modules
sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))

from WebWork import utils, db, dedup, fetcher, publisher, moderator
from formatting import html_escape
import pytest


# 1. Test title normalization and hash generation

def test_title_hash_normalization():
    t1 = "  Hello,    world! "
    t2 = "hello world"
    assert utils.normalize_whitespace(t1) == "Hello, world!"
    assert utils.compute_title_hash(t1) == utils.compute_title_hash(t2)
    assert dedup.calc_title_hash(t1) == dedup.calc_title_hash(t2)


# 2. Verify exists_url/guid/title_hash queries

def test_exists_queries():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    dedup.config.DEDUP_TITLE_MIN_LEN = 1
    item = {
        "url": "https://example.com/a",
        "guid": "guid-1",
        "title": "Title",
        "title_hash": dedup.calc_title_hash("Title"),
        "content": "Body",
        "source": "test",
        "published_at": "2024-01-01",
        "image_url": None,
    }
    db.insert_item(conn, item)
    assert db.exists_url(conn, item["url"])
    assert db.exists_guid(conn, item["guid"])
    assert db.exists_title_hash(conn, item["title_hash"])


# 3. Check image candidate ranking and Telegram text splitting

def test_first_http_url_ranking():
    candidates = ["", "ftp://x", "http://a", "https://b"]
    assert fetcher._first_http_url(candidates) == "http://a"


def test_publish_message_truncates_and_sends(monkeypatch):
    captured: list[str] = []

    def fake_api_post(method, payload, files=None):
        captured.append(payload.get("text", ""))
        return {"ok": True, "result": {"message_id": str(len(captured))}}

    monkeypatch.setattr(publisher, "_api_post", fake_api_post)
    monkeypatch.setattr(publisher.config, "TELEGRAM_MESSAGE_LIMIT", 120)
    monkeypatch.setattr(publisher.config, "TELEGRAM_PARSE_MODE", "HTML")
    monkeypatch.setattr(publisher.config, "ON_SEND_ERROR", "ignore")
    content = "<p>" + ("Текст " * 40) + "</p>"
    ok = publisher.publish_message(
        "123", "title", content, "https://e", cfg=publisher.config, meta={"rubric": "objects", "source_domain": "example.com"}
    )
    assert ok is True
    assert captured, "ожидался хотя бы один вызов отправки"
    for idx, text in enumerate(captured, 1):
        assert len(text) <= 120
        if idx == 1:
            payload = text.split(" ", 1)[1] if text.startswith("(") else text
            assert payload.startswith("Рубрика:")


def test_publish_message_failure(monkeypatch):
    def fake_api_post(method, payload, files=None):
        return None

    monkeypatch.setattr(publisher, "_api_post", fake_api_post)
    monkeypatch.setattr(publisher.config, "TELEGRAM_MESSAGE_LIMIT", 100)
    monkeypatch.setattr(publisher.config, "TELEGRAM_PARSE_MODE", "HTML")
    monkeypatch.setattr(publisher.config, "ON_SEND_ERROR", "ignore")
    ok = publisher.publish_message("123", "title", "body", "https://e", cfg=publisher.config)
    assert ok is False


def test_ensure_text_fits_parse_mode_markdown():
    text = "[link]" * 5
    trimmed = utils.ensure_text_fits_parse_mode(text, 20, "MarkdownV2")
    escaped = publisher._escape_markdown_v2(trimmed)  # pylint: disable=protected-access
    assert len(escaped) <= 20
    assert trimmed


def test_ensure_text_fits_parse_mode_html():
    text = "<b>" * 10
    trimmed = utils.ensure_text_fits_parse_mode(text, 20, "HTML")
    escaped = html_escape(trimmed)
    assert len(escaped) <= 20


def test_host_failure_stats(monkeypatch):
    fetcher.reset_host_fail_stats()

    def boom(*args, **kwargs):  # noqa: ANN001, ANN002 - signature mirrors net.get_text
        raise fetcher.requests.exceptions.ConnectionError("boom")  # type: ignore[attr-defined]

    url = "https://example.com/news"
    monkeypatch.setattr(fetcher.net, "get_text", boom)
    assert fetcher._fetch_text(url) == ""  # pylint: disable=protected-access

    stats = fetcher.get_host_fail_stats()
    host = "example.com"
    assert host in stats
    assert stats[host]["count"] == 1
    assert stats[host]["total_failures"] == 1

    # emulate cooldown expiration and a successful retry
    fetcher._HOST_FAILS[host] = time.time() - fetcher._FAIL_TTL - 1  # pylint: disable=protected-access

    def ok(*args, **kwargs):  # noqa: ANN001, ANN002
        return "ok"

    monkeypatch.setattr(fetcher.net, "get_text", ok)
    assert fetcher._fetch_text(url) == "ok"  # pylint: disable=protected-access

    stats_after = fetcher.get_host_fail_stats()
    assert stats_after[host]["count"] == 0
    assert stats_after[host]["recoveries"] >= 1
    assert fetcher.get_host_fail_stats(active_only=True) == {}


# 4. Simulate moderation state transitions

def _setup_mod_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_schema(conn)
    conn.executescript(
        """
        CREATE TABLE bot_state (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    return conn


def test_moderation_transitions(monkeypatch):
    if not hasattr(moderator, "_handle_callback_query"):
        pytest.skip("moderator callbacks not available")
    conn = _setup_mod_db()

    # prepare item in pending
    item = {"url": "https://e/1", "title": "t", "content": "c", "guid": "g", "source": "s"}
    mod_id = moderator.insert_pending(conn, item)

    # mock publisher and dedup
    monkeypatch.setattr(moderator.publisher, "publish_message", lambda **kw: True)
    monkeypatch.setattr(moderator.publisher, "answer_callback_query", lambda *a, **k: True)
    monkeypatch.setattr(moderator.publisher, "edit_moderation_message", lambda *a, **k: True)
    called = {}
    def fake_mark_published(**kw):
        called["yes"] = True
    monkeypatch.setattr(moderator.dedup, "mark_published", fake_mark_published)
    monkeypatch.setattr(moderator.config, "CHANNEL_ID", "123")

    cb = {"id": "1", "data": f"approve:{mod_id}", "message": {"chat": {"id": "1"}, "message_id": "10"}}
    moderator._handle_callback_query(cb, conn)
    row = conn.execute("SELECT status FROM moderation_queue WHERE id=?", (mod_id,)).fetchone()
    assert row["status"] == "approved"
    assert called.get("yes")

    # reject path
    item2 = {"url": "https://e/2", "title": "t2", "content": "c2", "guid": "g2", "source": "s"}
    mod_id2 = moderator.insert_pending(conn, item2)
    cb2 = {"id": "2", "data": f"reject:{mod_id2}", "message": {"chat": {"id": "1"}, "message_id": "11"}}
    moderator._handle_callback_query(cb2, conn)
    row = conn.execute("SELECT status FROM moderation_queue WHERE id=?", (mod_id2,)).fetchone()
    assert row["status"] == "rejected"

    # snoozed manually
    moderator.set_status(conn, mod_id2, "snoozed")
    row = conn.execute("SELECT status FROM moderation_queue WHERE id=?", (mod_id2,)).fetchone()
    assert row["status"] == "snoozed"

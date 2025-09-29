import logging
import pathlib
import sqlite3
import sys

import pytest

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

import db
import raw_pipeline


def _setup_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_schema(conn)
    return conn


@pytest.mark.parametrize("force_flag", [True, False])
def test_raw_pipeline_runs_when_forced(monkeypatch, tmp_path, force_flag):
    # Prepare configuration state
    monkeypatch.setattr(raw_pipeline.config, "RAW_STREAM_ENABLED", force_flag, raising=False)
    monkeypatch.setattr(raw_pipeline.config, "RAW_BYPASS_DEDUP", False, raising=False)
    monkeypatch.setattr(raw_pipeline.config, "RAW_REVIEW_CHAT_ID", "@raw_mod", raising=False)

    # Provide a sources file to mirror production behaviour when not enabled explicitly
    raw_file = tmp_path / "telegram_links_raw.txt"
    raw_file.write_text("https://t.me/s/sample_channel\n", encoding="utf-8")
    monkeypatch.setattr(raw_pipeline.config, "RAW_TELEGRAM_SOURCES_FILE", str(raw_file), raising=False)

    # Avoid network access
    def fake_fetch(session, source_url, timeout):
        return [
            raw_pipeline.RawPost(
                channel_url=source_url,
                alias="sample_channel",
                message_id="123",
                permalink=f"{source_url.rstrip('/')}/123",
                content_text="Test body",
                summary="",
                links=[],
                date_hint="",
                fetched_at=0.0,
            )
        ]

    monkeypatch.setattr(raw_pipeline, "fetch_tg_web_feed", fake_fetch)

    published = []

    def fake_publish(post):
        published.append(post)
        return True

    monkeypatch.setattr(raw_pipeline, "publish_to_raw_review", fake_publish)
    monkeypatch.setattr(raw_pipeline.http_client, "get_session", lambda: object())

    conn = _setup_connection()
    log = logging.getLogger("test.raw")

    # When RAW_STREAM_ENABLED is False, we force execution; otherwise normal run.
    raw_pipeline.run_raw_pipeline_once(
        None,
        conn,
        log,
        force=not force_flag,
        sources=["https://t.me/s/sample_channel"],
    )

    # The message should be published once.
    assert len(published) == 1


def test_raw_pipeline_detects_duplicates_across_url_variants(monkeypatch):
    monkeypatch.setattr(raw_pipeline.config, "RAW_STREAM_ENABLED", True, raising=False)
    monkeypatch.setattr(raw_pipeline.config, "RAW_BYPASS_DEDUP", False, raising=False)
    monkeypatch.setattr(raw_pipeline.config, "RAW_REVIEW_CHAT_ID", "@raw_mod", raising=False)

    def fake_fetch(session, source_url, timeout):
        return [
            raw_pipeline.RawPost(
                channel_url=source_url,
                alias="sample_channel",
                message_id="123",
                permalink=f"https://t.me/sample_channel/123",
                content_text="Test body",
                summary="",
                links=[],
                date_hint="",
                fetched_at=0.0,
            )
        ]

    monkeypatch.setattr(raw_pipeline, "fetch_tg_web_feed", fake_fetch)

    published = []

    def fake_publish(post):
        published.append(post)
        return True

    monkeypatch.setattr(raw_pipeline, "publish_to_raw_review", fake_publish)
    monkeypatch.setattr(raw_pipeline.http_client, "get_session", lambda: object())

    conn = _setup_connection()
    log = logging.getLogger("test.raw")

    raw_pipeline.run_raw_pipeline_once(
        None,
        conn,
        log,
        force=False,
        sources=["https://t.me/s/sample_channel"],
    )

    assert len(published) == 1

    raw_pipeline.run_raw_pipeline_once(
        None,
        conn,
        log,
        force=False,
        sources=["https://t.me/sample_channel"],
    )

    assert len(published) == 1


def test_raw_pipeline_skips_duplicate_links(monkeypatch):
    monkeypatch.setattr(raw_pipeline.config, "RAW_STREAM_ENABLED", True, raising=False)
    monkeypatch.setattr(raw_pipeline.config, "RAW_BYPASS_DEDUP", False, raising=False)
    monkeypatch.setattr(raw_pipeline.config, "RAW_REVIEW_CHAT_ID", "@raw_mod", raising=False)
    monkeypatch.setattr(raw_pipeline.config, "RAW_MAX_CHANNELS_PER_TICK", 5, raising=False)
    monkeypatch.setattr(raw_pipeline.config, "RAW_MAX_PER_CHANNEL", 5, raising=False)

    sources = [
        "https://t.me/s/channel_one",
        "https://t.me/s/channel_two",
    ]

    def fake_fetch(session, source_url, timeout):
        alias = "channel_one" if "one" in source_url else "channel_two"
        msg_id = "111" if alias == "channel_one" else "222"
        return [
            raw_pipeline.RawPost(
                channel_url=source_url,
                alias=alias,
                message_id=msg_id,
                permalink=f"https://t.me/{alias}/{msg_id}",
                content_text="Breaking news!",
                summary="Breaking news!",
                links=["https://example.com/news"],
                date_hint="",
                fetched_at=0.0,
            )
        ]

    monkeypatch.setattr(raw_pipeline, "fetch_tg_web_feed", fake_fetch)

    published: list[raw_pipeline.RawPost] = []

    def fake_publish(post):
        published.append(post)
        return True

    monkeypatch.setattr(raw_pipeline, "publish_to_raw_review", fake_publish)
    monkeypatch.setattr(raw_pipeline.http_client, "get_session", lambda: object())

    conn = _setup_connection()
    log = logging.getLogger("test.raw")

    raw_pipeline.run_raw_pipeline_once(
        None,
        conn,
        log,
        force=False,
        sources=sources,
    )

    # Only the first post should be published; the duplicate link is skipped.
    assert len(published) == 1
    assert published[0].alias == "channel_one"
    assert raw_pipeline.raw_link_is_dup(conn, raw_pipeline.canonical_url("https://example.com/news"))


def test_raw_pipeline_records_failed_publication_once(monkeypatch):
    monkeypatch.setattr(raw_pipeline.config, "RAW_STREAM_ENABLED", True, raising=False)
    monkeypatch.setattr(raw_pipeline.config, "RAW_BYPASS_DEDUP", False, raising=False)
    monkeypatch.setattr(raw_pipeline.config, "RAW_REVIEW_CHAT_ID", "@raw_mod", raising=False)

    def fake_fetch(session, source_url, timeout):
        return [
            raw_pipeline.RawPost(
                channel_url=source_url,
                alias="sample_channel",
                message_id="123",
                permalink=f"{source_url.rstrip('/')}/123",
                content_text="Test body",
                summary="",
                links=[],
                date_hint="",
                fetched_at=0.0,
            )
        ]

    monkeypatch.setattr(raw_pipeline, "fetch_tg_web_feed", fake_fetch)

    attempts: list[raw_pipeline.RawPost] = []

    def fake_publish(post):
        attempts.append(post)
        return False

    monkeypatch.setattr(raw_pipeline, "publish_to_raw_review", fake_publish)
    monkeypatch.setattr(raw_pipeline.http_client, "get_session", lambda: object())

    conn = _setup_connection()
    log = logging.getLogger("test.raw")

    raw_pipeline.run_raw_pipeline_once(
        None,
        conn,
        log,
        force=False,
        sources=["https://t.me/s/sample_channel"],
    )

    # A failed publish should not be retried on the next tick thanks to dedup.
    raw_pipeline.run_raw_pipeline_once(
        None,
        conn,
        log,
        force=False,
        sources=["https://t.me/s/sample_channel"],
    )

    assert len(attempts) == 1

def test_load_sources_by_branch_groups_channels(tmp_path):
    content = """
    # branch: alpha
    https://t.me/s/alpha_one

    [beta]
    https://t.me/s/beta_one
    https://t.me/s/alpha_one  # duplicate should be ignored in beta
    """
    sources_file = tmp_path / "raw_links.txt"
    sources_file.write_text(content, encoding="utf-8")

    grouped = raw_pipeline.load_sources_by_branch(str(sources_file))
    assert list(grouped.keys()) == ["alpha", "beta"]
    assert grouped["alpha"] == ["https://t.me/s/alpha_one"]
    assert grouped["beta"] == ["https://t.me/s/beta_one"]

    flattened = raw_pipeline.load_sources_file(str(sources_file))
    assert flattened == ["https://t.me/s/alpha_one", "https://t.me/s/beta_one"]

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

    # A second iteration should skip duplicates thanks to raw_dedup table.
    raw_pipeline.run_raw_pipeline_once(
        None,
        conn,
        log,
        force=not force_flag,
        sources=["https://t.me/s/sample_channel"],
    )

    assert len(published) == 1

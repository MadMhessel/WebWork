from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

import http_client

try:  # pragma: no cover - production style imports
    from . import config, utils, publisher
except ImportError:  # pragma: no cover - direct script execution
    import config  # type: ignore
    import utils  # type: ignore
    import publisher  # type: ignore


logger = logging.getLogger(__name__)


_SOURCE_SLICE_CURSOR = 0
_LAST_PRUNE_TS = 0.0


@dataclass(slots=True)
class RawPost:
    channel_url: str
    alias: str
    message_id: str
    permalink: str
    content_text: str
    summary: str
    links: List[str]
    date_hint: str
    fetched_at: float


def load_sources_file(path: str) -> List[str]:
    file_path = Path(path)
    if not file_path.exists():
        logger.warning("[RAW] sources file missing: %s", path)
        return []
    sources: List[str] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        sources.append(stripped)
    unique = list(dict.fromkeys(sources))
    return unique


def _round_robin_slice(sources: Sequence[str], limit: int) -> List[str]:
    global _SOURCE_SLICE_CURSOR
    if not sources:
        return []
    if limit <= 0:
        limit = len(sources)
    limit = min(limit, len(sources))
    start = _SOURCE_SLICE_CURSOR % len(sources)
    result: List[str] = []
    idx = start
    for _ in range(limit):
        result.append(sources[idx])
        idx = (idx + 1) % len(sources)
    _SOURCE_SLICE_CURSOR = idx
    return result


_INVISIBLE_RE = re.compile(r"[\u200b\u200c\u200d\uFEFF\u2060\u00ad]")


def _normalize_text(value: str, *, limit: int = 3072) -> str:
    value = utils.normalize_whitespace(value or "")
    value = _INVISIBLE_RE.sub("", value).lower()
    if len(value.encode("utf-8")) > limit:
        encoded = value.encode("utf-8")[:limit]
        value = encoded.decode("utf-8", errors="ignore")
    return value


def raw_build_msg_key(post: RawPost) -> str:
    message_id = (post.message_id or "").strip()
    if message_id:
        return f"id:{message_id}"
    normalized = _normalize_text(post.content_text)
    link_items = sorted({link.strip() for link in post.links if link.strip()})
    links_blob = "\n".join(link_items)
    blob = f"{normalized}\n{links_blob}\n{post.date_hint}".strip()
    digest = hashlib.sha1(blob.encode("utf-8")).hexdigest()
    return f"sha1:{digest}"


def raw_is_dup(conn, channel: str, msg_key: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM raw_dedup WHERE channel = ? AND msg_key = ? LIMIT 1",
        (channel, msg_key),
    )
    return cur.fetchone() is not None


def raw_mark_seen(conn, channel: str, msg_key: str, origin_url: str) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO raw_dedup(channel, msg_key, first_seen_ts, origin_url)
        VALUES(?, ?, strftime('%s','now'), ?)
        """,
        (channel, msg_key, origin_url),
    )
    conn.commit()


def raw_prune(conn, retention_days: int) -> int:
    if retention_days <= 0:
        return 0
    threshold = int(time.time() - retention_days * 86400)
    cur = conn.execute(
        "DELETE FROM raw_dedup WHERE first_seen_ts < ?",
        (threshold,),
    )
    conn.commit()
    return cur.rowcount or 0


def _resolve_alias(source_url: str) -> str:
    parsed = urlparse(source_url)
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return ""
    if parts[0] == "s" and len(parts) >= 2:
        return parts[1].lstrip("@")
    return parts[0].lstrip("@")


def _collect_links(block) -> List[str]:
    links: List[str] = []
    for a in block.select("a[href]"):
        href = a.get("href", "").strip()
        if href:
            links.append(href)
    for el in block.select("[data-attach-url]"):
        href = el.get("data-attach-url", "").strip()
        if href:
            links.append(href)
    for el in block.select("[data-thumb]"):
        href = el.get("data-thumb", "").strip()
        if href:
            links.append(href)
    return list(dict.fromkeys(links))


def _parse_message_block(block, *, channel_url: str, alias_fallback: str) -> Optional[RawPost]:
    link_el = block.select_one("a.tgme_widget_message_date")
    message_url = ""
    alias = alias_fallback
    message_id = ""
    if link_el is not None:
        message_url = link_el.get("href", "").strip()
        if message_url:
            parsed = urlparse(message_url)
            parts = [p for p in parsed.path.split("/") if p]
            if parts:
                if parts[0] == "s" and len(parts) >= 3:
                    alias = parts[1]
                    message_id = parts[2]
                elif len(parts) >= 2:
                    alias = parts[0]
                    message_id = parts[1]
            message_id = message_id.split("?")[0]

    data_post = block.get("data-post", "")
    if not message_id and data_post:
        _, _, maybe_id = data_post.partition("/")
        if maybe_id:
            message_id = maybe_id

    alias = (alias or alias_fallback or "").lstrip("@")
    permalink = message_url
    if alias and message_id:
        permalink = f"https://t.me/{alias}/{message_id}"
    elif alias:
        permalink = f"https://t.me/{alias}"
    else:
        permalink = channel_url

    time_el = link_el.select_one("time") if link_el else None
    date_hint = ""
    if time_el is not None:
        raw_dt = time_el.get("datetime", "").strip()
        if raw_dt:
            try:
                dt_obj = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
                date_hint = dt_obj.astimezone(timezone.utc).isoformat()
            except ValueError:
                date_hint = raw_dt
    if not date_hint:
        date_hint = datetime.now(timezone.utc).isoformat()

    text_el = block.select_one(".tgme_widget_message_text")
    content_text = ""
    if text_el is not None:
        content_text = text_el.get_text("\n", strip=True)
    if not content_text:
        caption_el = block.select_one(".tgme_widget_message_link_title")
        if caption_el is not None:
            content_text = caption_el.get_text("\n", strip=True)

    first_line = content_text.split("\n", 1)[0].strip()
    summary = first_line
    if text_el is not None:
        paragraphs = [p.strip() for p in content_text.split("\n") if p.strip()]
        if paragraphs:
            summary = paragraphs[0]

    links = _collect_links(block)

    return RawPost(
        channel_url=channel_url,
        alias=alias,
        message_id=message_id,
        permalink=permalink,
        content_text=content_text,
        summary=summary,
        links=links,
        date_hint=date_hint,
        fetched_at=time.time(),
    )


def fetch_tg_web_feed(session: requests.Session, url: str, *, timeout: tuple[float, float]) -> List[RawPost]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Cache-Control": "no-cache",
    }
    response = session.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    alias = _resolve_alias(url)
    posts: List[RawPost] = []
    for block in soup.select(".tgme_widget_message_wrap"):
        try:
            post = _parse_message_block(block, channel_url=url, alias_fallback=alias)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("[RAW] parse error: %s", exc)
            continue
        if post is None:
            continue
        posts.append(post)
    return posts


def _short_key_repr(msg_key: str) -> str:
    if not msg_key:
        return ""
    if ":" in msg_key:
        _, _, value = msg_key.partition(":")
    else:
        value = msg_key
    return value[:8]


def _publish_link(post: RawPost) -> bool:
    link = post.permalink or post.channel_url
    snippet = post.summary or post.content_text
    snippet = utils.normalize_whitespace(snippet or "")
    max_len = min(getattr(config, "TELEGRAM_MESSAGE_LIMIT", 4096) - 200, 1000)
    if len(snippet) > max_len:
        snippet = snippet[: max_len - 1].rstrip() + "…"
    text = link
    if snippet:
        text = f"{snippet}\n\n{link}".strip()
    try:
        publisher.tg_api(
            "sendMessage",
            chat_id=getattr(config, "RAW_REVIEW_CHAT_ID", ""),
            text=text,
            link_preview_options={
                "is_disabled": False,
                "url": link,
            },
        )
        logger.info("[RAW] publish: link -> OK")
        return True
    except Exception as exc:  # pragma: no cover - network dependent
        logger.warning("[RAW] publish: link -> FAIL %s", exc)
        return False


def publish_to_raw_review(post: RawPost) -> bool:
    strategy = getattr(config, "RAW_FORWARD_STRATEGY", "link")
    chat_id = getattr(config, "RAW_REVIEW_CHAT_ID", "")
    if not chat_id:
        logger.warning("[RAW] publish: RAW_REVIEW_CHAT_ID is empty")
        return False

    if (
        strategy in {"copy", "forward"}
        and post.alias
        and post.message_id
        and post.message_id.isdigit()
    ):
        method = "copyMessage" if strategy == "copy" else "forwardMessage"
        try:
            from_chat_id = publisher.get_from_chat_id(post.alias)
            publisher.tg_api(
                method,
                chat_id=chat_id,
                from_chat_id=from_chat_id,
                message_id=int(post.message_id),
            )
            logger.info("[RAW] publish: %s -> OK", strategy)
            return True
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("[RAW] publish: %s -> FAIL %s", strategy, exc)

    return _publish_link(post)


def _maybe_prune(conn) -> None:
    global _LAST_PRUNE_TS
    interval = int(getattr(config, "RAW_PRUNE_INTERVAL_SEC", 3600))
    if interval <= 0:
        return
    now = time.time()
    if now - _LAST_PRUNE_TS < interval:
        return
    removed = raw_prune(conn, int(getattr(config, "DEDUP_RETENTION_DAYS", 45)))
    logger.info("[RAW] prune: removed=%d older_than=%dd", removed, int(getattr(config, "DEDUP_RETENTION_DAYS", 45)))
    _LAST_PRUNE_TS = now


def run_raw_pipeline_once(
    session: Optional[requests.Session],
    conn,
    log: logging.Logger,
    *,
    force: bool = False,
    sources: Optional[Sequence[str]] = None,
) -> None:
    """Execute a single iteration of the RAW pipeline.

    Parameters
    ----------
    session:
        Optional :class:`requests.Session` to reuse network connections.
    conn:
        SQLite connection used for deduplication bookkeeping.
    log:
        Logger instance for structured diagnostics.
    force:
        When ``True`` the pipeline runs even if ``RAW_STREAM_ENABLED`` is not
        enabled in the configuration.  This is used by the main loop to
        automatically process ``telegram_links_raw.txt`` when it exists.
    sources:
        Optional pre-loaded list of source URLs.  When ``None`` the function
        loads sources from ``RAW_TELEGRAM_SOURCES_FILE``.
    """

    if not force and not getattr(config, "RAW_STREAM_ENABLED", False):
        return

    if sources is None:
        sources = load_sources_file(getattr(config, "RAW_TELEGRAM_SOURCES_FILE", ""))

    if not sources:
        _maybe_prune(conn)
        return
    session = session or http_client.get_session()
    timeout = (
        float(getattr(config, "HTTP_TIMEOUT_CONNECT", 5.0)),
        float(getattr(config, "HTTP_TIMEOUT_READ", 65.0)),
    )
    limit_channels = int(getattr(config, "RAW_MAX_CHANNELS_PER_TICK", 3))
    limit_per_channel = int(getattr(config, "RAW_MAX_PER_CHANNEL", 10))
    channel_timeout = float(getattr(config, "RAW_CHANNEL_TIMEOUT_SEC", 30.0))
    for source_url in _round_robin_slice(sources, limit_channels):
        start_ts = time.monotonic()
        try:
            posts = fetch_tg_web_feed(session, source_url, timeout=timeout)
            log.info("[RAW] fetch: %s -> OK %d", source_url, len(posts))
        except requests.RequestException as exc:
            log.warning("[RAW] fetch: %s -> FAIL %s", source_url, exc)
            continue
        except Exception as exc:
            log.warning("[RAW] fetch: %s -> FAIL %s", source_url, exc)
            continue

        new_count = 0
        for post in posts:
            if time.monotonic() - start_ts > channel_timeout:
                log.warning("[RAW] fetch: %s -> watchdog timeout reached", source_url)
                break
            msg_key = raw_build_msg_key(post)
            if not getattr(config, "RAW_BYPASS_DEDUP", False) and raw_is_dup(conn, source_url, msg_key):
                log.info(
                    "[RAW] dup: %s key=%s — SKIP",
                    source_url,
                    _short_key_repr(msg_key),
                )
                continue
            if publish_to_raw_review(post):
                raw_mark_seen(conn, source_url, msg_key, post.permalink or source_url)
                new_count += 1
            if new_count >= limit_per_channel:
                break

    _maybe_prune(conn)


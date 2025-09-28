"""Routing helpers for publishing posts to Telegram channels."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from .config import load
from .logging_setup import log_kv
from .publisher import send_photo_with_caption, send_text
from .utils.formatting import TG_CAPTION_LIMIT, TG_TEXT_LIMIT

logger = logging.getLogger("webwork.router")
_tg_cfg, _ = load()


def build_text_message(post: Dict[str, Any]) -> str:
    """Build long-form message for the text channel."""

    title = (post.get("title") or "").strip()
    lead = (post.get("summary") or post.get("lead") or "").strip()
    url = (post.get("url") or "").strip()
    parts = [part for part in (title, lead, url) if part]
    return "\n\n".join(parts)


def build_media_caption(post: Dict[str, Any]) -> str:
    """Build short caption for media channel."""

    title = (post.get("title") or "").strip()
    url = (post.get("url") or "").strip()
    caption = f"{title}\n{url}".strip()
    return caption


def resolve_media(post: Dict[str, Any]) -> Optional[Any]:
    """Resolve media payload (photo/video) for Telegram API."""

    return (
        post.get("image_file_id")
        or post.get("image_url")
        or post.get("video_file_id")
        or post.get("video_url")
        or None
    )


def route_and_publish(api, post: Dict[str, Any], *, is_raw: bool = False) -> None:
    """Route approved posts into text and media channels."""

    request_id = str(uuid.uuid4())[:8]
    source = post.get("source") or post.get("origin") or "unknown"
    dedup = post.get("dedup_key") or ""

    log_kv(
        logger,
        logging.INFO,
        "route start",
        req=request_id,
        is_raw=is_raw,
        src=source,
        dedup=dedup,
        text_channel=_tg_cfg.channel_text_id,
        media_channel=_tg_cfg.channel_media_id,
    )

    if is_raw:
        log_kv(logger, logging.INFO, "raw branch bypassed in router", req=request_id)
        return

    if _tg_cfg.enable_text:
        text_msg = build_text_message(post)
        log_kv(
            logger,
            logging.DEBUG,
            "prepare text",
            req=request_id,
            length=len(text_msg),
            limit=TG_TEXT_LIMIT,
        )
        send_text(api, _tg_cfg.channel_text_id, text_msg)

    if _tg_cfg.enable_media:
        media = resolve_media(post)
        caption = build_media_caption(post)
        if media:
            log_kv(
                logger,
                logging.DEBUG,
                "prepare media",
                req=request_id,
                caption_len=len(caption),
                limit=TG_CAPTION_LIMIT,
                has_media=True,
            )
            send_photo_with_caption(api, _tg_cfg.channel_media_id, media, caption)
        else:
            log_kv(
                logger,
                logging.WARNING,
                "no media, fallback to text",
                req=request_id,
                caption_len=len(caption),
                has_media=False,
            )
            send_text(api, _tg_cfg.channel_media_id, caption)

    log_kv(
        logger,
        logging.INFO,
        "route done",
        req=request_id,
        title=(post.get("title") or "")[:160],
    )

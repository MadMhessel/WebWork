"""Centralised environment configuration helpers for WebWork."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)


def _getenv(*names: str, required: bool = False, default: Optional[str] = None) -> Optional[str]:
    for idx, name in enumerate(names):
        value = os.getenv(name)
        if value:
            if len(names) > 1 and idx != 0:
                logger.warning(
                    "ENV alias %s used for %s; please rename to %s",
                    name,
                    names[0],
                    names[0],
                )
            return value
    if required and default is None:
        raise RuntimeError(f"Missing required env var: one of {names}")
    return default


def _as_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class TelegramCfg:
    token: str
    parse_mode: str
    channel_text_id: str
    channel_media_id: str
    enable_text: bool
    enable_media: bool
    review_chat_id: Optional[str] = None
    legacy_channel_id: Optional[str] = None


@dataclass(frozen=True)
class HttpCfg:
    timeout: float
    retry_total: int
    backoff_factor: float


@dataclass(frozen=True)
class DedupCfg:
    near_duplicates_enabled: bool
    near_duplicate_threshold: float


@dataclass(frozen=True)
class RawStreamCfg:
    enabled: bool
    review_chat_id: Optional[str]
    bypass_filters: bool
    bypass_dedup: bool


@dataclass(frozen=True)
class LogCfg:
    level: str
    json: bool


@dataclass(frozen=True)
class AppConfig:
    telegram: TelegramCfg
    http: HttpCfg
    dedup: DedupCfg
    raw: RawStreamCfg
    log: LogCfg


@lru_cache()
def load_all() -> AppConfig:
    parse_mode_raw = _getenv("PARSE_MODE", "TELEGRAM_PARSE_MODE", default="HTML") or "HTML"
    legacy_channel = _getenv("CHANNEL_CHAT_ID", "CHANNEL_ID")
    text_channel = _getenv("CHANNEL_TEXT_CHAT_ID")
    media_channel = _getenv("CHANNEL_MEDIA_CHAT_ID")
    if not text_channel and legacy_channel:
        logging.warning(
            "CHANNEL_TEXT_CHAT_ID missing; falling back to legacy channel id %s",
            legacy_channel,
        )
        text_channel = legacy_channel
    if not media_channel and legacy_channel:
        logging.warning(
            "CHANNEL_MEDIA_CHAT_ID missing; falling back to legacy channel id %s",
            legacy_channel,
        )
        media_channel = legacy_channel
    text_channel = (text_channel or "").strip()
    media_channel = (media_channel or "").strip()

    telegram_cfg = TelegramCfg(
        token=_getenv("TELEGRAM_BOT_TOKEN", "BOT_TOKEN", default="") or "",
        parse_mode=parse_mode_raw.strip() or "HTML",
        channel_text_id=text_channel.strip(),
        channel_media_id=media_channel.strip(),
        enable_text=_as_bool(_getenv("ENABLE_TEXT_CHANNEL", default="1"), True),
        enable_media=_as_bool(_getenv("ENABLE_MEDIA_CHANNEL", default="1"), True),
        review_chat_id=_getenv("REVIEW_CHAT_ID", "MOD_CHAT_ID"),
        legacy_channel_id=legacy_channel,
    )

    http_timeout = _getenv("HTTP_TIMEOUT", default=_getenv("HTTP_TIMEOUT_READ", default="10")) or "10"
    http_retry = _getenv("HTTP_RETRY_TOTAL", default="3") or "3"
    http_backoff = _getenv("HTTP_BACKOFF", default="0.5") or "0.5"
    http_cfg = HttpCfg(
        timeout=float(http_timeout),
        retry_total=int(http_retry),
        backoff_factor=float(http_backoff),
    )

    dedup_cfg = DedupCfg(
        near_duplicates_enabled=_as_bool(_getenv("NEAR_DUPLICATES_ENABLED", default="false")),
        near_duplicate_threshold=float(_getenv("NEAR_DUPLICATE_THRESHOLD", default="0.9") or "0.9"),
    )

    raw_cfg = RawStreamCfg(
        enabled=_as_bool(_getenv("RAW_STREAM_ENABLED", default="false")),
        review_chat_id=_getenv("RAW_REVIEW_CHAT_ID", "REVIEW_CHAT_ID"),
        bypass_filters=_as_bool(_getenv("RAW_BYPASS_FILTERS", default="false")),
        bypass_dedup=_as_bool(_getenv("RAW_BYPASS_DEDUP", default="false")),
    )

    log_cfg = LogCfg(
        level=(_getenv("LOG_LEVEL", default="INFO") or "INFO").upper(),
        json=_as_bool(_getenv("LOG_JSON"), False),
    )

    return AppConfig(telegram=telegram_cfg, http=http_cfg, dedup=dedup_cfg, raw=raw_cfg, log=log_cfg)


def load() -> tuple[TelegramCfg, LogCfg]:
    cfg = load_all()
    return cfg.telegram, cfg.log


def dedup_cfg() -> DedupCfg:
    return load_all().dedup


def raw_stream_cfg() -> RawStreamCfg:
    return load_all().raw


def http_cfg() -> HttpCfg:
    return load_all().http

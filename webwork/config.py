"""Centralised environment configuration helpers for WebWork."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)


def _env(*names: str, required: bool = False, default: Optional[str] = None) -> Optional[str]:
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


@dataclass(frozen=True)
class TelegramCfg:
    token: str
    channel_id: str
    review_chat_id: Optional[str]
    parse_mode: str


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
class AppConfig:
    telegram: TelegramCfg
    http: HttpCfg
    dedup: DedupCfg
    raw: RawStreamCfg


@lru_cache()
def load_all() -> AppConfig:
    telegram_parse_mode = (_env("PARSE_MODE", "TELEGRAM_PARSE_MODE", default="HTML") or "HTML").strip()
    telegram_cfg = TelegramCfg(
        token=_env("TELEGRAM_BOT_TOKEN", "BOT_TOKEN", default="" ) or "",
        channel_id=_env("CHANNEL_CHAT_ID", "CHANNEL_ID", default="") or "",
        review_chat_id=_env("REVIEW_CHAT_ID", "MOD_CHAT_ID"),
        parse_mode=telegram_parse_mode or "HTML",
    )
    http_timeout_str = _env("HTTP_TIMEOUT", default=_env("HTTP_TIMEOUT_READ", default="10")) or "10"
    http_retry_str = _env("HTTP_RETRY_TOTAL", default="3") or "3"
    http_backoff_str = _env("HTTP_BACKOFF", default="0.5") or "0.5"
    http_cfg = HttpCfg(
        timeout=float(http_timeout_str),
        retry_total=int(http_retry_str),
        backoff_factor=float(http_backoff_str),
    )
    dedup_cfg = DedupCfg(
        near_duplicates_enabled=(
            (_env("NEAR_DUPLICATES_ENABLED", default="false") or "false").lower()
            in {"1", "true", "yes", "on"}
        ),
        near_duplicate_threshold=float(_env("NEAR_DUPLICATE_THRESHOLD", default="0.9") or "0.9"),
    )
    raw_cfg = RawStreamCfg(
        enabled=(
            (_env("RAW_STREAM_ENABLED", default="false") or "false").lower()
            in {"1", "true", "yes", "on"}
        ),
        review_chat_id=_env("REVIEW_CHAT_ID", "RAW_REVIEW_CHAT_ID"),
        bypass_filters=(
            (_env("RAW_BYPASS_FILTERS", default="false") or "false").lower()
            in {"1", "true", "yes", "on"}
        ),
        bypass_dedup=(
            (_env("RAW_BYPASS_DEDUP", default="false") or "false").lower()
            in {"1", "true", "yes", "on"}
        ),
    )
    return AppConfig(telegram=telegram_cfg, http=http_cfg, dedup=dedup_cfg, raw=raw_cfg)


def load() -> tuple[TelegramCfg, HttpCfg]:
    cfg = load_all()
    return cfg.telegram, cfg.http


def dedup_cfg() -> DedupCfg:
    return load_all().dedup


def raw_stream_cfg() -> RawStreamCfg:
    return load_all().raw

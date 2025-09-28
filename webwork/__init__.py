"""Core package for shared WebWork helpers."""

from __future__ import annotations

from functools import lru_cache
from typing import Tuple

from .config import (
    AppConfig,
    HttpCfg,
    LogCfg,
    TelegramCfg,
    dedup_cfg,
    load_all,
    raw_stream_cfg,
)


@lru_cache()
def _cached_config() -> AppConfig:
    return load_all()


def telegram_cfg() -> TelegramCfg:
    return _cached_config().telegram


def http_cfg() -> HttpCfg:
    return _cached_config().http


def log_cfg() -> LogCfg:
    return _cached_config().log


def dedup_config():
    return dedup_cfg()


def raw_config():
    return raw_stream_cfg()


def load() -> Tuple[TelegramCfg, LogCfg]:
    cfg = _cached_config()
    return cfg.telegram, cfg.log

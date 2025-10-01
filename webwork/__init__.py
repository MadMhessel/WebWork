"""Core package for shared WebWork helpers."""

from __future__ import annotations

from functools import lru_cache
from importlib import import_module
from typing import TYPE_CHECKING, Tuple

if TYPE_CHECKING:  # pragma: no cover - imported for type checkers only
    from .config import AppConfig, HttpCfg, LogCfg, TelegramCfg


def _config_module():
    """Return the lazily-imported configuration module."""

    return import_module(__name__ + ".config")


@lru_cache()
def _cached_config() -> "AppConfig":
    return _config_module().load_all()


def telegram_cfg() -> "TelegramCfg":
    return _cached_config().telegram


def http_cfg() -> "HttpCfg":
    return _cached_config().http


def log_cfg() -> "LogCfg":
    return _cached_config().log


def raw_config():
    return _cached_config().raw


def load() -> Tuple["TelegramCfg", "LogCfg"]:
    cfg = _cached_config()
    return cfg.telegram, cfg.log


try:
    dedup_config = import_module(__name__ + ".dedup_config")
except Exception:  # pragma: no cover - optional module
    dedup_config = None  # type: ignore[assignment]


__all__ = [
    "dedup_config",
    "http_cfg",
    "load",
    "log_cfg",
    "raw_config",
    "telegram_cfg",
]

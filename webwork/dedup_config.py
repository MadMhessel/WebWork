"""Lazy loader for deduplication configuration."""

from __future__ import annotations

from functools import lru_cache
from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from .config import DedupCfg


def _config_module():
    return import_module(__name__.rsplit(".", 1)[0] + ".config")


@lru_cache()
def load() -> "DedupCfg":
    """Return the deduplication configuration section."""

    return _config_module().dedup_cfg()


__all__ = ["load"]

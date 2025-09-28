"""Logging helpers with KV/JSON formatting and secret masking."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict

from .config import load

_SECRET_KEY_PATTERN = re.compile(r"(TOKEN|SECRET|API_KEY)$", re.IGNORECASE)
_CHAT_KEY_PATTERN = re.compile(r"CHAT_ID$", re.IGNORECASE)
_PUBLIC_CHAT_PREFIXES = ("@",)


class SecretsFilter(logging.Filter):
    """Filter that masks secrets found in environment variables."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401 - signature mandated by logging
        message = record.getMessage()
        for key, value in os.environ.items():
            if not value:
                continue
            if _SECRET_KEY_PATTERN.search(key):
                message = message.replace(value, "***")
                continue
            if _CHAT_KEY_PATTERN.search(key) and not value.startswith(_PUBLIC_CHAT_PREFIXES):
                message = message.replace(value, "***")
                continue
        record.msg = message
        record.args = ()
        return True


class KVFormatter(logging.Formatter):
    """Formatter that appends key-value context pairs."""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        ctx = getattr(record, "ctx", None)
        if ctx and isinstance(ctx, dict):
            kv = " ".join(f"{key}={value}" for key, value in ctx.items())
            if kv:
                return f"{base} | {kv}"
        return base


def setup_logging() -> None:
    """Configure root logging handlers according to env settings."""

    _, log_cfg = load()
    level = getattr(logging, log_cfg.level.upper(), logging.INFO)
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(level)

    handler = logging.StreamHandler()
    handler.addFilter(SecretsFilter())

    if log_cfg.json:

        class JSONFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:  # noqa: D401
                payload: Dict[str, Any] = {
                    "level": record.levelname,
                    "name": record.name,
                    "message": record.getMessage(),
                    "time": self.formatTime(record, "%Y-%m-%d %H:%M:%S"),
                }
                ctx = getattr(record, "ctx", None)
                if isinstance(ctx, dict):
                    payload.update(ctx)
                return json.dumps(payload, ensure_ascii=False)

        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            KVFormatter(
                fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                datefmt="%H:%M:%S",
            )
        )

    root.addHandler(handler)


def log_kv(logger: logging.Logger, level: int, message: str, **ctx: Any) -> None:
    """Emit log record with structured context in ``ctx``."""

    logger.log(level, message, extra={"ctx": ctx})

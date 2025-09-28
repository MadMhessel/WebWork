"""Lightweight logging helpers with secret masking."""

from __future__ import annotations

import logging
import os
import re
from typing import Iterable

_SECRET_KEY_PATTERN = re.compile(r"(TOKEN|SECRET|API_KEY)$", re.IGNORECASE)
_CHAT_ID_PATTERN = re.compile(r"CHAT_ID$", re.IGNORECASE)
_PUBLIC_CHAT_PREFIXES = ("@",)


class SecretsFilter(logging.Filter):
    """Filter that masks secrets in log records."""

    def __init__(self) -> None:
        super().__init__()
        self._secret_values = _collect_secret_values()

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401 - signature mandated by logging
        message = record.getMessage()
        masked = _mask_values(message, self._secret_values)
        record.msg = masked
        record.args = ()
        return True


def _collect_secret_values() -> Iterable[str]:
    values: list[str] = []
    for key, value in os.environ.items():
        if not value:
            continue
        if _SECRET_KEY_PATTERN.search(key):
            values.append(value)
            continue
        if _CHAT_ID_PATTERN.search(key) and not value.startswith(_PUBLIC_CHAT_PREFIXES):
            values.append(value)
    return values


def _mask_values(message: str, secrets: Iterable[str]) -> str:
    masked = message
    for secret in secrets:
        masked = masked.replace(secret, "***")
    return masked


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger().addFilter(SecretsFilter())

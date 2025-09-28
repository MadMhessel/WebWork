"""Centralized logging configuration for the WebWork project."""

from __future__ import annotations

import logging
import logging.config
import re
import time
from pathlib import Path
from typing import Any, Dict

try:  # pragma: no cover - package import for production/runtime
    from . import config  # type: ignore
except ImportError:  # pragma: no cover - direct script execution
    import config  # type: ignore

from webwork.logging_setup import SecretsFilter

__all__ = ["init_logging", "get_logger", "mask_secrets", "audit"]


class UTCFormatter(logging.Formatter):
    """Formatter that always uses UTC timestamps."""

    converter = staticmethod(time.gmtime)


_TOKEN_PATTERN = re.compile(r"bot(\d+):([A-Za-z0-9_-]+)")
_SECRET_PATTERN = re.compile(r"(token=)([^&\s]+)", re.IGNORECASE)

_DEFAULT_LOGGER = "webwork.app"
_LOGGING_INITIALIZED = False
_LOG_DIR: Path | None = None


def mask_secrets(text: Any) -> Any:
    """Mask sensitive substrings (like Telegram tokens) in ``text``."""

    if not isinstance(text, str):
        return text

    masked = _TOKEN_PATTERN.sub(lambda m: f"bot{m.group(1)}:***", text)
    masked = _SECRET_PATTERN.sub(lambda m: f"{m.group(1)}***", masked)
    return masked


def _build_file_handler(
    log_dir: Path,
    filename: str,
    cfg: Any,
    *,
    level: str,
    formatter: str,
) -> Dict[str, Any]:
    rotate_bytes = int(getattr(cfg, "LOG_ROTATE_BYTES", 10 * 1024 * 1024))
    backup_count = int(getattr(cfg, "LOG_BACKUP_COUNT", 7))
    use_time_rotate = bool(getattr(cfg, "LOG_TIME_ROTATE", False))

    handler: Dict[str, Any]
    if use_time_rotate:
        when = getattr(cfg, "LOG_TIME_WHEN", "midnight")
        time_backup_count = int(getattr(cfg, "LOG_TIME_BACKUP_COUNT", backup_count))
        handler = {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "filename": str(log_dir / filename),
            "when": when,
            "backupCount": time_backup_count,
            "utc": True,
            "encoding": "utf-8",
            "delay": True,
            "level": level,
            "formatter": formatter,
        }
    else:
        handler = {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(log_dir / filename),
            "maxBytes": rotate_bytes,
            "backupCount": backup_count,
            "encoding": "utf-8",
            "delay": True,
            "level": level,
            "formatter": formatter,
        }
    return handler


def init_logging(cfg: Any = config) -> None:
    """Initialise project-wide logging based on ``cfg`` settings."""

    global _LOGGING_INITIALIZED, _LOG_DIR

    if _LOGGING_INITIALIZED:
        return

    log_dir_name = getattr(cfg, "LOG_DIR_NAME", "logs") or "logs"
    log_dir = Path(__file__).resolve().parent / log_dir_name
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter_name = "standard"
    level = getattr(cfg, "LOG_LEVEL", "INFO").upper()
    console_level = getattr(cfg, "LOG_CONSOLE_LEVEL", level).upper()
    sql_enabled = bool(getattr(cfg, "LOG_SQL_DEBUG", False))

    handlers: Dict[str, Any] = {
        "app_file": _build_file_handler(log_dir, "app.log", cfg, level="INFO", formatter=formatter_name),
        "err_file": _build_file_handler(
            log_dir,
            "errors.log",
            cfg,
            level="WARNING",
            formatter=formatter_name,
        ),
        "bot_file": _build_file_handler(log_dir, "bot.log", cfg, level="INFO", formatter=formatter_name),
        "audit_file": _build_file_handler(log_dir, "audit.log", cfg, level="INFO", formatter=formatter_name),
        "console": {
            "class": "logging.StreamHandler",
            "level": console_level,
            "formatter": formatter_name,
            "stream": "ext://sys.stderr",
        },
    }

    if sql_enabled:
        handlers["sql_file"] = _build_file_handler(
            log_dir, "sql.log", cfg, level="DEBUG", formatter=formatter_name
        )
    else:
        handlers["sql_file"] = {
            "class": "logging.NullHandler",
            "level": "DEBUG",
        }

    logging_config: Dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            formatter_name: {
                "()": "logging_setup.UTCFormatter",
                "format": "%(asctime)s %(levelname)s %(name)s: %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            }
        },
        "handlers": handlers,
        "loggers": {
            "webwork.app": {
                "handlers": ["app_file", "err_file", "console"],
                "level": level,
                "propagate": False,
            },
            "webwork.bot": {
                "handlers": ["bot_file", "err_file", "console"],
                "level": level,
                "propagate": False,
            },
            "webwork.sql": {
                "handlers": ["sql_file"],
                "level": "DEBUG",
                "propagate": False,
            },
            "webwork.audit": {
                "handlers": ["audit_file"],
                "level": "INFO",
                "propagate": False,
            },
        },
        "root": {
            "level": "WARNING",
            "handlers": ["console", "err_file"],
        },
    }

    logging.config.dictConfig(logging_config)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("feedparser").setLevel(logging.INFO)
    logging.getLogger().addFilter(SecretsFilter())

    _LOGGING_INITIALIZED = True
    _LOG_DIR = log_dir

    get_logger().info("Логирование инициализировано (директория: %s)", log_dir)


def _normalize_logger_name(name: str) -> str:
    if not name:
        return _DEFAULT_LOGGER
    if name.startswith("webwork."):
        return name
    if name == "webwork":
        return _DEFAULT_LOGGER
    if name.startswith("webwork"):
        return name
    return f"{_DEFAULT_LOGGER}.{name}"


def get_logger(name: str = _DEFAULT_LOGGER) -> logging.Logger:
    """Return a namespaced logger within the ``webwork`` hierarchy."""

    return logging.getLogger(_normalize_logger_name(name))


def audit(event: str, **fields: Any) -> None:
    """Write a structured audit trail entry."""

    logger = get_logger("webwork.audit")
    parts = [event]
    for key, value in sorted(fields.items()):
        if value is None:
            continue
        masked_value = mask_secrets(str(value))
        parts.append(f"{key}={masked_value}")
    logger.info(" | ".join(parts))


def get_log_dir() -> Path | None:
    """Expose resolved log directory for callers that need it."""

    return _LOG_DIR

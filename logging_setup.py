# -*- coding: utf-8 -*-
import logging  # стандартный модуль логирования
import sys
from . import config

_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"

def setup_logging() -> None:
    root = logging.getLogger()
    if getattr(root, "_newsbot_logging_inited", False):
        return

    level = getattr(logging, config.LOG_LEVEL, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT))

    root.setLevel(level)
    root.addHandler(handler)

    # Шуманим болтливые либы
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("feedparser").setLevel(logging.INFO)

    root._newsbot_logging_inited = True
    logging.getLogger(__name__).info("Логирование инициализировано (уровень: %s)", config.LOG_LEVEL)

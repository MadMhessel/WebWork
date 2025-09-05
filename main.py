# -*- coding: utf-8 -*-
import argparse
import logging
import sys
import time
from typing import Dict, List, Tuple

from . import config, logging_setup, fetcher, filters, dedup, db
from .utils import normalize_whitespace, compute_title_hash

logger = logging.getLogger(__name__)

# Паблишер необязательный: если модуль есть — используем, нет — просто логируем.
try:
    from . import publisher  # type: ignore
except Exception:  # pragma: no cover
    publisher = None  # type: ignore

def _publisher_init() -> None:
    if not publisher:
        return
    for fn in ("init", "setup", "initialize"):
        if hasattr(publisher, fn):
            getattr(publisher, fn)()
            break
    logger.info("Telegram клиент инициализирован.")

def _publisher_send(item: Dict) -> bool:
    if not publisher:
        return False
    # пробуем несколько известных сигнатур
    for fn in ("publish", "send", "enqueue", "queue_send", "push"):
        if hasattr(publisher, fn):
            try:
                getattr(publisher, fn)(item)  # type: ignore
                return True
            except Exception as ex:  # pragma: no cover
                logger.exception("Ошибка отправки (%s): %s", fn, ex)
                return False
    return False

def run_once(conn) -> Tuple[int, int, int, int, int, int, int, int]:
    items = fetcher.fetch_all(config.SOURCES, limit_per_source=config.FETCH_LIMIT_PER_SOURCE)
    logger.info("Всего получено материалов: %d", len(items))

    seen_urls: set = set()
    seen_title_hashes: set = set()

    cnt_relevant = 0
    cnt_dup_inpack_url = 0
    cnt_dup_inpack_title = 0
    cnt_dup_db = 0
    cnt_queued = 0
    cnt_published = 0
    cnt_not_sent = 0
    cnt_errors = 0

    for it in items:
        try:
            src = it.get("source") or ""
            url = (it.get("url") or "").strip()
            guid = (it.get("guid") or "").strip()
            title = normalize_whitespace(it.get("title") or "")
            content = normalize_whitespace(it.get("content") or "")
            image_url = it.get("image_url")

            ok, region_ok, topic_ok, reason = filters.is_relevant_for_source(title, content, src, config)
            if not ok:
                logger.info("[SKIP] %s | %s | причина: %s", src, title, reason)
                continue
            cnt_relevant += 1

            # дубликаты в пакете
            thash = compute_title_hash(title) if title else ""
            if url and url in seen_urls:
                cnt_dup_inpack_url += 1
                logger.info("[SKIP] %s | %s | причина: дубль URL в пакете", src, title)
                continue
            if thash and thash in seen_title_hashes:
                cnt_dup_inpack_title += 1
                logger.info("[SKIP] %s | %s | причина: почти дубль заголовка в пакете", src, title)
                continue

            seen_urls.add(url)
            if thash:
                seen_title_hashes.add(thash)

            # дубликаты в БД
            if dedup.is_duplicate(url, guid, title, conn):
                cnt_dup_db += 1
                logger.error("[ERROR] url=%s | дубль в БД", url)
                continue

            # отправка
            item_clean = {
                "source": src,
                "guid": guid,
                "url": url,
                "title": title,
                "content": content,
                "published_at": it.get("published_at") or "",
                "image_url": image_url,
            }
            sent = _publisher_send(item_clean)
            if sent:
                cnt_published += 1
            else:
                cnt_not_sent += 1

            # запоминаем в БД
            dedup.remember(conn, item_clean)

        except KeyboardInterrupt:
            raise
        except Exception as ex:
            cnt_errors += 1
            logger.exception("[ERROR] url=%s | %s", it.get("url", ""), ex)

    logger.info(
        "ИТОГО: получено=%d, релевантные=%d, дублей_в_пакете_URL=%d, почти_дублей_в_пакете=%d, "
        "дублей_в_БД=%d, в_очередь=%d, опубликовано=%d, ошибок=%d, не_отправлено=%d",
        len(items), cnt_relevant, cnt_dup_inpack_url, cnt_dup_inpack_title,
        cnt_dup_db, cnt_queued, cnt_published, cnt_errors, cnt_not_sent
    )
    return (len(items), cnt_relevant, cnt_dup_inpack_url, cnt_dup_inpack_title,
            cnt_dup_db, cnt_queued, cnt_published, cnt_errors)

def main() -> int:
    logging_setup.setup_logging()

    # Поднимаем БД
    conn = db.connect()
    db.init_schema(conn)

    # Инициализируем паблишер (если он есть)
    _publisher_init()

    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="Бесконечный цикл с паузой")
    args = parser.parse_args()

    if not args.loop:
        run_once(conn)
        return 0

    logger.info("Старт бесконечного цикла. Пауза: %d сек.", config.LOOP_DELAY_SECS)
    while True:
        try:
            db.init_schema(conn)  # на всякий случай
            _publisher_init()
            run_once(conn)
            time.sleep(config.LOOP_DELAY_SECS)
        except KeyboardInterrupt:
            logger.warning("Остановка по Ctrl+C")
            break
        except Exception as ex:
            logger.exception("Неожиданная ошибка цикла: %s", ex)
            time.sleep(15)

    return 0

if __name__ == "__main__":
    sys.exit(main())

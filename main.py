# -*- coding: utf-8 -*-
import argparse
import logging
import sys
import time
import threading
from typing import Dict, List, Tuple

try:
    from . import (
        config,
        logging_setup,
        fetcher,
        filters,
        dedup,
        db,
        rewrite,
        images,
        tagging,
        classifieds,
    )
    from . import moderator as moderation, bot_updates
    from .utils import normalize_whitespace, compute_title_hash
    try:
        from . import publisher  # type: ignore
    except Exception:  # pragma: no cover
        publisher = None  # type: ignore
except ImportError:  # pragma: no cover
    import config, logging_setup, fetcher, filters, dedup, db, rewrite, images, tagging, classifieds  # type: ignore
    import moderator as moderation  # type: ignore
    import bot_updates  # type: ignore
    from utils import normalize_whitespace, compute_title_hash  # type: ignore
    try:
        import publisher  # type: ignore
    except Exception:  # pragma: no cover
        publisher = None  # type: ignore

logger = logging.getLogger(__name__)


def _publisher_init() -> None:
    if publisher and hasattr(publisher, "init_telegram_client"):
        publisher.init_telegram_client()
        logger.info("Telegram клиент инициализирован.")


def _publisher_send_direct(item: Dict) -> bool:
    if not publisher:
        return False
    chat_id = getattr(config, "CHANNEL_CHAT_ID", "") or getattr(config, "CHANNEL_ID", "")
    return publisher.publish_message(
        chat_id,
        item.get("title", ""),
        item.get("content", ""),
        item.get("url", ""),
        item.get("image_url"),
        image_bytes=item.get("image_bytes"),
        image_mime=item.get("image_mime"),
        credit=item.get("credit"),
        cfg=config,
    )

def run_once(conn) -> Tuple[int, int, int, int, int, int, int, int]:
    items_iter = fetcher.fetch_all(
        config.SOURCES, limit_per_source=config.FETCH_LIMIT_PER_SOURCE
    )

    seen_urls: set = set()
    seen_title_hashes: set = set()

    cnt_total = 0
    cnt_relevant = 0
    cnt_dup_inpack_url = 0
    cnt_dup_inpack_title = 0
    cnt_dup_db = 0
    cnt_queued = 0
    cnt_published = 0
    cnt_not_sent = 0
    cnt_errors = 0
    image_start = images.image_stats["with_image"]

    for it in items_iter:
        cnt_total += 1
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

            # дополнительные теги и глобальные стоп-слова
            tags, has_neg = tagging.extract_tags(f"{title}\n{content}")
            if has_neg:
                logger.info("[SKIP] %s | %s | причина: нежелательная тематика", src, title)
                continue

            if classifieds.is_classified(title, content, url):
                logger.info("[SKIP] %s | %s | причина: рекламная публикация", src, title)
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
                "source_id": src,
                "guid": guid,
                "url": url,
                "title": title,
                "content": content,
                "summary": it.get("summary") or "",
                "published_at": it.get("published_at") or "",
                "image_url": image_url,
                "tags": list(tags),
            }

            img_info = images.resolve_image(item_clean, conn)
            item_clean["image_url"] = img_info.get("image_url", "")
            if img_info.get("tg_file_id"):
                item_clean["tg_file_id"] = img_info["tg_file_id"]
            if img_info.get("image_hash"):
                item_clean["image_hash"] = img_info["image_hash"]
            if img_info.get("bytes"):
                item_clean["image_bytes"] = img_info["bytes"]
                if img_info.get("mime"):
                    item_clean["image_mime"] = img_info.get("mime")
            if img_info.get("credit"):
                item_clean["credit"] = img_info["credit"]

            item_clean = rewrite.maybe_rewrite_item(item_clean, config)

            if getattr(config, "ENABLE_MODERATION", False):
                mod_id = moderation.enqueue_and_preview(item_clean, conn)
                if mod_id:
                    cnt_queued += 1
                else:
                    cnt_not_sent += 1
            else:
                sent = _publisher_send_direct(item_clean)
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

    with_image = images.image_stats["with_image"] - image_start
    logger.info(
        "ИТОГО: получено=%d, релевантные=%d, дублей_в_пакете_URL=%d, почти_дублей_в_пакете=%d, "
        "дублей_в_БД=%d, в_очередь=%d, опубликовано=%d, ошибок=%d, не_отправлено=%d, с_картинкой=%d",
        cnt_total,
        cnt_relevant,
        cnt_dup_inpack_url,
        cnt_dup_inpack_title,
        cnt_dup_db,
        cnt_queued,
        cnt_published,
        cnt_errors,
        cnt_not_sent,
        with_image,
    )
    return (
        cnt_total,
        cnt_relevant,
        cnt_dup_inpack_url,
        cnt_dup_inpack_title,
        cnt_dup_db,
        cnt_queued,
        cnt_published,
        cnt_errors,
    )

def main() -> int:
    logging_setup.setup_logging()
    config.validate_config()

    # Поднимаем БД
    conn = db.connect()
    db.init_schema(conn)

    # Инициализируем паблишер (если он есть)
    _publisher_init()

    stop_event = threading.Event()
    updates_thread = None
    if getattr(config, "ENABLE_MODERATION", False):
        updates_thread = threading.Thread(target=bot_updates.run, args=(stop_event,), daemon=True)
        updates_thread.start()

    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="Бесконечный цикл с паузой")
    args = parser.parse_args()

    if not args.loop:
        run_once(conn)
        return 0

    logger.info("Старт бесконечного цикла. Пауза: %d сек.", config.LOOP_DELAY_SECS)
    while True:
        try:
            run_once(conn)
            time.sleep(config.LOOP_DELAY_SECS)
        except KeyboardInterrupt:
            logger.warning("Остановка по Ctrl+C")
            break
        except Exception as ex:
            logger.exception("Неожиданная ошибка цикла: %s", ex)
            time.sleep(15)

    stop_event.set()
    if updates_thread is not None:
        updates_thread.join(timeout=5)
    return 0

if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
import argparse
import sys
import time
import threading
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import bot_updates
import classifieds
import config
import dedup
import db
import filters
import http_client
import moderation
import moderator
import raw_pipeline
import rewrite
import tagging
from utils import compute_title_hash, normalize_whitespace
try:  # pragma: no cover - publisher may be optional in tests
    import publisher  # type: ignore
except Exception:  # pragma: no cover
    publisher = None  # type: ignore
from logging_setup import get_logger, init_logging

logger = get_logger(__name__)


def _normalize_domain_value(domain: str) -> str:
    domain = (domain or "").strip().lower()
    if domain.startswith("www."):
        domain = domain[4:]
    try:
        domain = domain.encode("idna").decode("ascii")
    except Exception:
        pass
    return domain


def _publisher_init() -> None:
    if publisher and hasattr(publisher, "init_telegram_client"):
        publisher.init_telegram_client()
        logger.info("Telegram клиент инициализирован.")


def _publisher_send_direct(item: Dict) -> bool:
    if not publisher:
        return False
    chat_id = getattr(config, "CHANNEL_CHAT_ID", "") or getattr(config, "CHANNEL_ID", "")
    mid = publisher.publish_structured_item(
        chat_id,
        item,
        cfg=config,
        rewrite_item=False,
    )
    return bool(mid)

def run_once(conn) -> Tuple[int, int, int, int, int, int, int, int]:
    raw_force_run = False
    raw_sources: Optional[List[str]] = None
    if not getattr(config, "RAW_STREAM_ENABLED", False):
        raw_path = getattr(config, "RAW_TELEGRAM_SOURCES_FILE", "")
        if raw_path:
            try:
                raw_sources = raw_pipeline.load_sources_file(raw_path)
            except Exception as exc:
                logger.warning("[RAW] sources load error: %s", exc)
                raw_sources = []
            else:
                raw_force_run = bool(raw_sources)

    if getattr(config, "RAW_STREAM_ENABLED", False) or raw_force_run:
        logger.info(
            "[RAW] pipeline: start (force=%s, sources=%d)",
            raw_force_run,
            len(raw_sources or []),
        )
        try:
            raw_pipeline.run_raw_pipeline_once(
                http_client.get_session(),
                conn,
                logger,
                force=raw_force_run,
                sources=raw_sources if raw_force_run else None,
            )
        except Exception:
            logger.exception("[RAW] pipeline error")

    items_iter: Iterable[Dict[str, Any]]
    if not getattr(config, "TELEGRAM_AUTO_FETCH", True):
        logger.info(
            "TELEGRAM_AUTO_FETCH=0, загрузка Telegram пропущена; парсинг сайтов отключён."
        )
        items_iter = []
    else:
        from telegram_fetcher import fetch_from_telegram

        items_iter = list(
            fetch_from_telegram(
                getattr(config, "TELEGRAM_MODE", "mtproto"),
                getattr(config, "TELEGRAM_LINKS_FILE", "telegram_links.txt"),
                getattr(config, "TELEGRAM_FETCH_LIMIT", 30),
            )
        )
        logger.info(
            "Загрузка из Telegram: получено %d элементов (парсинг сайтов отключён)",
            len(items_iter),
        )

    seen_urls: set = set()
    seen_title_hashes: set = set()

    sources_by_name = getattr(config, "SOURCES_BY_NAME", {})
    sources_by_domain = getattr(config, "SOURCES_BY_DOMAIN_ALL", {})

    cnt_total = 0
    cnt_relevant = 0
    cnt_dup_inpack_url = 0
    cnt_dup_inpack_title = 0
    cnt_dup_db = 0
    cnt_queued = 0
    cnt_published = 0
    cnt_not_sent = 0
    cnt_errors = 0
    for it in items_iter:
        cnt_total += 1
        try:
            src = it.get("source") or ""
            url = (it.get("url") or "").strip()
            guid = (it.get("guid") or "").strip()
            title = normalize_whitespace(it.get("title") or "")
            content = normalize_whitespace(it.get("content") or "")
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
                logger.info("[DUP_DB] url=%s | найден в истории", url)
                continue

            # отправка
            filter_meta = {
                "region": bool(region_ok),
                "topic": bool(topic_ok),
            }

            source_meta = dict(sources_by_name.get(src, {}))
            domain = _normalize_domain_value(source_meta.get("source_domain"))

            if not domain:
                parsed = urlparse(url)
                domain = _normalize_domain_value(parsed.hostname or "")

            domain_sources = sources_by_domain.get(domain, []) if domain else []
            if domain_sources:
                matched = None
                if url:
                    for candidate in domain_sources:
                        cand_url = str(candidate.get("url") or "").strip()
                        if cand_url and url.startswith(cand_url):
                            matched = candidate
                            break
                if not matched:
                    matched = domain_sources[0]
                combined = dict(source_meta)
                combined.update(matched)
                source_meta = combined
                domain = source_meta.get("source_domain", domain)

            if not domain:
                parsed = urlparse(url)
                domain = _normalize_domain_value(parsed.hostname or "")

            allowed_rubrics = list(source_meta.get("rubrics_allowed", [])) or [
                "objects",
                "persons",
                "kazusy",
            ]
            rubric = "objects" if "objects" in allowed_rubrics else allowed_rubrics[0]

            trust_level = 0
            try:
                trust_level = int(source_meta.get("trust_level") or 0)
            except (TypeError, ValueError):
                trust_level = 0

            item_clean = {
                "source": src,
                "source_id": src,
                "guid": guid,
                "url": url,
                "title": title,
                "content": content,
                "summary": it.get("summary") or "",
                "published_at": it.get("published_at") or "",
                "tags": list(tags),
                "reasons": filter_meta,
                "rubric": rubric,
                "source_domain": domain or "",
                "trust_level": trust_level,
            }

            block = moderation.run_blocklists(item_clean)
            if block.blocked:
                logger.info(
                    "[BLOCK] %s | %s | причина: %s",
                    src,
                    title,
                    block.label or block.pattern,
                )
                continue

            flags_hold = moderation.run_hold_flags(item_clean)
            flags_deprio = moderation.run_deprioritize_flags(item_clean)
            all_flags = flags_hold + flags_deprio
            sources_ctx: List[Dict[str, Any]] = []
            if source_meta:
                meta_copy = dict(source_meta)
                if domain and not meta_copy.get("source_domain"):
                    meta_copy["source_domain"] = domain
                if trust_level >= 3:
                    meta_copy.setdefault("is_official", True)
                sources_ctx.append(meta_copy)
            confirmation = moderation.needs_confirmation(
                item_clean, all_flags, {"sources": sources_ctx, "flags": all_flags}
            )
            trust_summary = moderation.summarize_trust(sources_ctx)
            quality_note = any(flag.requires_quality_note for flag in all_flags)

            item_clean["moderation_flags"] = [flag.to_dict() for flag in all_flags]
            item_clean["needs_confirmation"] = confirmation.needs_confirmation
            item_clean["confirmation_reasons"] = confirmation.reasons
            item_clean["quality_note_required"] = quality_note
            item_clean["trust_summary"] = trust_summary

            item_clean = rewrite.maybe_rewrite_item(item_clean, config)

            remember_success = False
            if getattr(config, "ENABLE_MODERATION", False):
                mod_id = moderator.enqueue_and_preview(item_clean, conn)
                if mod_id:
                    cnt_queued += 1
                    remember_success = True
                else:
                    cnt_not_sent += 1
            else:
                sent = _publisher_send_direct(item_clean)
                if sent:
                    cnt_published += 1
                    remember_success = True
                else:
                    cnt_not_sent += 1

            if remember_success:
                # запоминаем в БД только успешно поставленные/отправленные материалы
                dedup.remember(conn, item_clean)

        except KeyboardInterrupt:
            raise
        except Exception as ex:
            cnt_errors += 1
            logger.exception("[ERROR] url=%s | %s", it.get("url", ""), ex)

    logger.info(
        "ИТОГО: получено=%d, релевантные=%d, дублей_в_пакете_URL=%d, почти_дублей_в_пакете=%d, "
        "дублей_в_БД=%d, в_очередь=%d, опубликовано=%d, ошибок=%d, не_отправлено=%d",
        cnt_total,
        cnt_relevant,
        cnt_dup_inpack_url,
        cnt_dup_inpack_title,
        cnt_dup_db,
        cnt_queued,
        cnt_published,
        cnt_errors,
        cnt_not_sent,
    )

    items_ttl = int(getattr(config, "ITEM_RETENTION_DAYS", 0))
    dedup_ttl = int(getattr(config, "DEDUP_RETENTION_DAYS", 0))
    if items_ttl > 0 or dedup_ttl > 0:
        db.prune_old_records(
            conn,
            items_ttl_days=items_ttl,
            dedup_ttl_days=dedup_ttl,
            batch_limit=int(getattr(config, "DB_PRUNE_BATCH", 500)),
        )

    active_failures = fetcher.get_host_fail_stats(active_only=True)
    if active_failures:
        parts = []
        now = time.time()
        for host, data in active_failures.items():
            first_ts = data.get("first_failure_ts") or now
            duration_min = max(0, int((now - first_ts) / 60))
            parts.append(
                f"{host}: {data.get('count', 0)} попыток, {duration_min} мин"
            )
        logger.warning("Источники с повторными сбоями: %s", "; ".join(parts))

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
    init_logging(config)
    get_logger("webwork.app").info("Логирование инициализировано")
    config.validate_config()

    if getattr(config, "DRY_RUN", False):
        logger.warning(
            "[DRY-RUN: READY] Сообщения НЕ будут отправлены в Telegram — режим тестирования включен."
        )

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

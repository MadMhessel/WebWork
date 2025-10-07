# import-shim for flat layout
if __name__ == "__main__" or __package__ is None:
    import os, sys
    sys.path.insert(0, os.path.dirname(__file__))

import argparse
import os
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass
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
from logging_setup import get_logger, init_logging
from utils import compute_title_hash, normalize_whitespace
from rate_limiter import configure_global as configure_rate_limiter

try:
    from fetcher import get_host_fail_stats as _get_host_fail_stats
except Exception as exc:  # pragma: no cover - optional dependency failures
    _FETCHER_IMPORT_ERROR = exc
    _get_host_fail_stats = None
else:
    _FETCHER_IMPORT_ERROR = None

try:  # pragma: no cover - publisher may be optional in tests
    import publisher
except Exception:  # pragma: no cover
    publisher = None  # type: ignore[assignment]

logger = get_logger(__name__)

if _FETCHER_IMPORT_ERROR:
    logger.warning(
        "Сводка повторных сбоев источников недоступна: %s",
        _FETCHER_IMPORT_ERROR,
    )


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
    if getattr(config, "DRY_RUN", False):
        logger.info(
            "[DRY-RUN] Сообщение не отправлено (chat_id=%s, title=%s)",
            chat_id,
            item.get("title", "")[:120],
        )
        return False
    mid = publisher.publish_structured_item(
        chat_id,
        item,
        cfg=config,
        rewrite_item=False,
    )
    return bool(mid)

@dataclass
class RunSummary:
    totals: Tuple[int, int, int, int, int, int, int, int]
    stages: Dict[str, int]

    def __iter__(self):  # pragma: no cover - legacy unpacking
        return iter(self.totals)


def _trace_run_once(message: str) -> None:
    trace_message = f"[RUN_ONCE TRACE] {message}"
    print(trace_message)
    sys.stdout.flush()
    logger.info(trace_message)


@contextmanager
def _run_once_stage(name: str):
    _trace_run_once(f"{name}: start")
    try:
        yield
    except SystemExit as exc:
        _trace_run_once(f"{name}: SystemExit detected (code={exc.code})")
        logger.exception("run_once stage %s raised SystemExit", name)
        raise
    except BaseException as exc:  # noqa: B902 - we want to log all unexpected exits
        _trace_run_once(f"{name}: error: {exc!r}")
        logger.exception("run_once stage %s failed", name)
        raise
    else:
        _trace_run_once(f"{name}: finish")


def run_once(
    conn,
    *,
    raw_mode: str = "auto",
) -> RunSummary:
    _trace_run_once("run_once: start")
    try:
        with _run_once_stage("raw configuration"):
            raw_mode = raw_mode or "auto"
            raw_only = raw_mode == "only"
            raw_skip = raw_mode == "skip"
            raw_force_run = raw_only
            raw_sources: Optional[List[str]] = None
            raw_stream_enabled = getattr(config, "RAW_STREAM_ENABLED", False)
            if not raw_skip and (raw_only or not raw_stream_enabled):
                raw_path = getattr(config, "RAW_TELEGRAM_SOURCES_FILE", "")
                _trace_run_once(
                    f"raw configuration: evaluate sources file (path={raw_path or 'none'})"
                )
                if raw_path:
                    try:
                        raw_sources = raw_pipeline.load_sources_file(raw_path)
                    except Exception as exc:
                        _trace_run_once(
                            f"raw configuration: sources load error detected: {exc!r}"
                        )
                        logger.warning("[RAW] sources load error: %s", exc)
                        raw_sources = []
                    else:
                        raw_force_run = raw_force_run or bool(raw_sources)
                        _trace_run_once(
                            "raw configuration: sources loaded successfully"
                        )
            should_run_raw = (not raw_skip) and (raw_stream_enabled or raw_force_run)

        with _run_once_stage("raw pipeline execution"):
            if should_run_raw:
                logger.info(
                    "[RAW] pipeline: start (force=%s, sources=%d)",
                    raw_force_run,
                    len(raw_sources or []),
                )
                _trace_run_once(
                    "raw pipeline execution: invoking run_raw_pipeline_once"
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
                    _trace_run_once("raw pipeline execution: exception raised")
                    logger.exception("[RAW] pipeline error")
                else:
                    _trace_run_once("raw pipeline execution: completed")
            else:
                _trace_run_once(
                    "raw pipeline execution: skipped (should_run_raw is False)"
                )

        stage_counts: Dict[str, int] = {
            "in": 0,
            "after_fetch": 0,
            "after_filters": 0,
            "after_dedup": 0,
            "after_moderation": 0,
            "to_publish": 0,
        }

        with _run_once_stage("raw only shortcut"):
            if raw_only:
                _trace_run_once("raw only shortcut: returning empty summary")
                return RunSummary((0, 0, 0, 0, 0, 0, 0, 0), stage_counts)

        with _run_once_stage("items fetch"):
            items_iter: Iterable[Dict[str, Any]]
            if not getattr(config, "TELEGRAM_AUTO_FETCH", True):
                logger.info(
                    "TELEGRAM_AUTO_FETCH=0, загрузка Telegram пропущена; парсинг сайтов отключён."
                )
                _trace_run_once(
                    "items fetch: TELEGRAM_AUTO_FETCH disabled, using empty list"
                )
                items_iter = []
            else:
                mode = getattr(config, "TELEGRAM_MODE", "mtproto")
                _trace_run_once(f"items fetch: mode={mode}")
                if mode == "mtproto" and (
                    int(getattr(config, "TELETHON_API_ID", 0) or 0) <= 0
                    or not getattr(config, "TELETHON_API_HASH", "")
                ):
                    logger.warning(
                        "TELEGRAM_MODE=mtproto, но TELETHON_API_ID/TELETHON_API_HASH не заданы. "
                        "Пропускаем загрузку из Telegram."
                    )
                    _trace_run_once(
                        "items fetch: mtproto mode missing credentials, skip fetch"
                    )
                    items_iter = []
                else:
                    from telegram_fetcher import (
                        FetchOptions,
                        TelegramFetchTimeoutError,
                        fetch_from_telegram,
                    )

                    fetch_options = FetchOptions(
                        max_channels_per_iter=int(
                            max(
                                1,
                                getattr(
                                    config, "TELEGRAM_MAX_CHANNELS_PER_ITER", 50
                                ),
                            )
                        ),
                        fetch_workers=int(
                            max(1, getattr(config, "TELEGRAM_FETCH_WORKERS", 5))
                        ),
                        messages_per_channel=int(
                            max(
                                1,
                                getattr(
                                    config, "TELEGRAM_MESSAGES_PER_CHANNEL", 30
                                ),
                            )
                        ),
                        rate=float(
                            max(0.1, getattr(config, "TELEGRAM_RATE_LIMIT", 25.0))
                        ),
                        flood_sleep_threshold=int(
                            max(
                                0,
                                getattr(
                                    config, "TELETHON_FLOOD_SLEEP_THRESHOLD", 30
                                ),
                            )
                        ),
                    )
                    _trace_run_once(
                        "items fetch: invoking fetch_from_telegram (may block)"
                    )
                    fetch_timeout = float(
                        max(
                            1.0,
                            getattr(
                                config,
                                "TELEGRAM_FETCH_TIMEOUT",
                                fetch_options.timeout_seconds or 30.0,
                            ),
                        )
                    )
                    logger.info(
                        "items fetch: starting fetch_from_telegram (timeout=%ss)",
                        fetch_timeout,
                    )
                    try:
                        _trace_run_once(
                            "items fetch: about to call fetch_from_telegram"
                        )
                        fetch_result_iterable = fetch_from_telegram(
                            mode,
                            getattr(
                                config, "TELEGRAM_LINKS_FILE", "telegram_links.txt"
                            ),
                            fetch_options.messages_per_channel,
                            options=fetch_options,
                            timeout=fetch_timeout,
                        )
                        _trace_run_once(
                            "items fetch: fetch_from_telegram returned control to run_once"
                        )
                        items_iter = list(fetch_result_iterable)
                        _trace_run_once(
                            f"items fetch: fetch_from_telegram iterable materialized ({len(items_iter)} items)"
                        )
                    except TelegramFetchTimeoutError:
                        logger.error(
                            "items fetch: fetch_from_telegram timed out after %s seconds",
                            fetch_timeout,
                            exc_info=True,
                        )
                        _trace_run_once(
                            "items fetch: fetch_from_telegram timed out, using empty list"
                        )
                        items_iter = []
                    except SystemExit as exc:
                        _trace_run_once(
                            f"items fetch: fetch_from_telegram raised SystemExit: {exc!r}"
                        )
                        logger.exception(
                            "items fetch: fetch_from_telegram raised SystemExit"
                        )
                        raise
                    except KeyboardInterrupt as exc:
                        _trace_run_once(
                            f"items fetch: fetch_from_telegram interrupted by KeyboardInterrupt: {exc!r}"
                        )
                        logger.exception(
                            "items fetch: fetch_from_telegram raised KeyboardInterrupt"
                        )
                        raise
                    except Exception as exc:
                        logger.exception("items fetch: fetch_from_telegram failed")
                        _trace_run_once(
                            f"items fetch: fetch_from_telegram raised Exception ({exc!r}), using empty list"
                        )
                        items_iter = []
                    except BaseException as exc:
                        _trace_run_once(
                            f"items fetch: fetch_from_telegram raised BaseException: {exc!r}"
                        )
                        logger.exception(
                            "items fetch: fetch_from_telegram raised BaseException"
                        )
                        raise
                    else:
                        logger.info(
                            "items fetch: fetch_from_telegram finished, received %d items",
                            len(items_iter),
                        )
                        _trace_run_once(
                            f"items fetch: fetch_from_telegram returned {len(items_iter)} items"
                        )
                    finally:
                        _trace_run_once(
                            "items fetch: fetch_from_telegram try-block complete"
                        )

        stage_counts["in"] = len(items_iter)
        stage_counts["after_fetch"] = len(items_iter)

        _trace_run_once(
            f"run_once: post-fetch initialization start (items={len(items_iter)})"
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

        with _run_once_stage("items processing loop"):
            _trace_run_once(
                f"items processing loop: start iterating over {len(items_iter)} items"
            )
            for it in items_iter:
                cnt_total += 1
                item_stage_prefix = f"item #{cnt_total}"
                try:
                    src = it.get("source") or ""
                    url = (it.get("url") or "").strip()
                    guid = (it.get("guid") or "").strip()
                    title = normalize_whitespace(it.get("title") or "")
                    content = normalize_whitespace(it.get("content") or "")
                    _trace_run_once(
                        f"{item_stage_prefix}: relevance check start (source={src})"
                    )
                    ok, region_ok, topic_ok, reason = filters.is_relevant_for_source(
                        title, content, src, config
                    )
                    if not ok:
                        logger.info(
                            "[SKIP] %s | %s | причина: %s", src, title, reason
                        )
                        _trace_run_once(
                            f"{item_stage_prefix}: skipped by relevance ({reason})"
                        )
                        continue

                    _trace_run_once(
                        f"{item_stage_prefix}: tagging/extraction start"
                    )
                    tags, has_neg = tagging.extract_tags(f"{title}\n{content}")
                    if has_neg:
                        logger.info(
                            "[SKIP] %s | %s | причина: нежелательная тематика",
                            src,
                            title,
                        )
                        _trace_run_once(
                            f"{item_stage_prefix}: skipped by negative tag"
                        )
                        continue

                    if classifieds.is_classified(title, content, url):
                        logger.info(
                            "[SKIP] %s | %s | причина: рекламная публикация",
                            src,
                            title,
                        )
                        _trace_run_once(
                            f"{item_stage_prefix}: skipped by classifieds"
                        )
                        continue
                    cnt_relevant += 1
                    stage_counts["after_filters"] += 1

                    thash = compute_title_hash(title) if title else ""
                    if url and url in seen_urls:
                        cnt_dup_inpack_url += 1
                        logger.info(
                            "[SKIP] %s | %s | причина: дубль URL в пакете",
                            src,
                            title,
                        )
                        _trace_run_once(
                            f"{item_stage_prefix}: skipped by in-pack URL duplicate"
                        )
                        continue
                    if thash and thash in seen_title_hashes:
                        cnt_dup_inpack_title += 1
                        logger.info(
                            "[SKIP] %s | %s | причина: почти дубль заголовка в пакете",
                            src,
                            title,
                        )
                        _trace_run_once(
                            f"{item_stage_prefix}: skipped by in-pack title duplicate"
                        )
                        continue

                    seen_urls.add(url)
                    if thash:
                        seen_title_hashes.add(thash)

                    if dedup.is_duplicate(url, guid, title, conn):
                        cnt_dup_db += 1
                        logger.info("[DUP_DB] url=%s | найден в истории", url)
                        _trace_run_once(
                            f"{item_stage_prefix}: skipped by DB duplicate"
                        )
                        continue
                    stage_counts["after_dedup"] += 1

                    filter_meta = {
                        "region": bool(region_ok),
                        "topic": bool(topic_ok),
                    }

                    source_meta = dict(sources_by_name.get(src, {}))
                    domain = _normalize_domain_value(
                        source_meta.get("source_domain")
                    )

                    if not domain:
                        parsed = urlparse(url)
                        domain = _normalize_domain_value(parsed.hostname or "")

                    domain_sources = (
                        sources_by_domain.get(domain, []) if domain else []
                    )
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
                    rubric = (
                        "objects" if "objects" in allowed_rubrics else allowed_rubrics[0]
                    )

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

                    _trace_run_once(
                        f"{item_stage_prefix}: moderation checks start"
                    )
                    block = moderation.run_blocklists(item_clean)
                    if block.blocked:
                        logger.info(
                            "[BLOCK] %s | %s | причина: %s",
                            src,
                            title,
                            block.label or block.pattern,
                        )
                        _trace_run_once(
                            f"{item_stage_prefix}: blocked by moderation ({block.label or block.pattern})"
                        )
                        continue
                    stage_counts["after_moderation"] += 1

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
                    quality_note = any(
                        flag.requires_quality_note for flag in all_flags
                    )

                    item_clean["moderation_flags"] = [
                        flag.to_dict() for flag in all_flags
                    ]
                    item_clean["needs_confirmation"] = (
                        confirmation.needs_confirmation
                    )
                    item_clean["confirmation_reasons"] = confirmation.reasons
                    item_clean["quality_note_required"] = quality_note
                    item_clean["trust_summary"] = trust_summary

                    _trace_run_once(
                        f"{item_stage_prefix}: rewrite/maybe_rewrite start"
                    )
                    item_clean = rewrite.maybe_rewrite_item(item_clean, config)

                    remember_success = False
                    if getattr(config, "ENABLE_MODERATION", False):
                        _trace_run_once(
                            f"{item_stage_prefix}: enqueue moderator (may block)"
                        )
                        mod_id = moderator.enqueue_and_preview(item_clean, conn)
                        if mod_id:
                            cnt_queued += 1
                            remember_success = True
                            _trace_run_once(
                                f"{item_stage_prefix}: queued for moderation"
                            )
                        else:
                            cnt_not_sent += 1
                            _trace_run_once(
                                f"{item_stage_prefix}: NOT queued for moderation"
                            )
                    else:
                        _trace_run_once(
                            f"{item_stage_prefix}: direct publish attempt"
                        )
                        sent = _publisher_send_direct(item_clean)
                        if sent:
                            cnt_published += 1
                            remember_success = True
                            _trace_run_once(
                                f"{item_stage_prefix}: published directly"
                            )
                        else:
                            cnt_not_sent += 1
                            _trace_run_once(
                                f"{item_stage_prefix}: direct publish failed"
                            )

                    if remember_success:
                        _trace_run_once(
                            f"{item_stage_prefix}: remember in dedup"
                        )
                        dedup.remember(conn, item_clean)
                        stage_counts["to_publish"] += 1

                except KeyboardInterrupt:
                    raise
                except SystemExit as exc:
                    _trace_run_once(
                        f"{item_stage_prefix}: SystemExit detected (code={exc.code})"
                    )
                    raise
                except Exception as ex:
                    cnt_errors += 1
                    logger.exception("[ERROR] url=%s | %s", it.get("url", ""), ex)
                    _trace_run_once(
                        f"{item_stage_prefix}: exception encountered ({ex!r})"
                    )

        with _run_once_stage("summary logging"):
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

            logger.info(
                "[PIPELINE] in=%d after_fetch=%d after_filters=%d after_dedup=%d after_moderation=%d to_publish=%d",
                stage_counts["in"],
                stage_counts["after_fetch"],
                stage_counts["after_filters"],
                stage_counts["after_dedup"],
                stage_counts["after_moderation"],
                stage_counts["to_publish"],
            )

        with _run_once_stage("database pruning"):
            items_ttl = int(getattr(config, "ITEM_RETENTION_DAYS", 0))
            dedup_ttl = int(getattr(config, "DEDUP_RETENTION_DAYS", 0))
            if items_ttl > 0 or dedup_ttl > 0:
                _trace_run_once(
                    f"database pruning: start (items_ttl={items_ttl}, dedup_ttl={dedup_ttl})"
                )
                db.prune_old_records(
                    conn,
                    items_ttl_days=items_ttl,
                    dedup_ttl_days=dedup_ttl,
                    batch_limit=int(getattr(config, "DB_PRUNE_BATCH", 500)),
                )
                _trace_run_once("database pruning: completed")
            else:
                _trace_run_once(
                    "database pruning: skipped (ttl values are zero or negative)"
                )

        with _run_once_stage("host failure stats"):
            active_failures: Dict[str, Dict[str, float]] = {}
            if _get_host_fail_stats is not None:
                _trace_run_once(
                    "host failure stats: fetching active host failure statistics"
                )
                try:
                    active_failures = _get_host_fail_stats(active_only=True)
                except Exception:
                    logger.exception(
                        "Не удалось получить статистику повторных сбоев источников"
                    )
                    active_failures = {}
                    _trace_run_once(
                        "host failure stats: exception while fetching statistics"
                    )
                else:
                    _trace_run_once(
                        f"host failure stats: fetched {len(active_failures)} records"
                    )
            else:
                _trace_run_once(
                    "host failure stats: fetcher not available (import error)"
                )
            if active_failures:
                parts = []
                now = time.time()
                for host, data in active_failures.items():
                    first_ts = data.get("first_failure_ts") or now
                    duration_min = max(0, int((now - first_ts) / 60))
                    parts.append(
                        f"{host}: {data.get('count', 0)} попыток, {duration_min} мин"
                    )
                logger.warning(
                    "Источники с повторными сбоями: %s", "; ".join(parts)
                )

        summary = RunSummary(
            (
                cnt_total,
                cnt_relevant,
                cnt_dup_inpack_url,
                cnt_dup_inpack_title,
                cnt_dup_db,
                cnt_queued,
                cnt_published,
                cnt_errors,
            ),
            stage_counts,
        )
        _trace_run_once("run_once: summary prepared, returning from function")
        return summary
    except SystemExit as exc:
        _trace_run_once(f"run_once: SystemExit propagated (code={exc.code})")
        raise
    finally:
        _trace_run_once("run_once: finish")


def main() -> int:
    init_logging(config)
    get_logger("webwork.app").info("Логирование инициализировано")

    parser = argparse.ArgumentParser()
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--loop", action="store_true", help="Бесконечный цикл с паузой")
    mode_group.add_argument("--once", action="store_true", help="Выполнить один проход и выйти")
    parser.add_argument("--dry-run", action="store_true", help="Не отправлять сообщения в Telegram")
    parser.add_argument(
        "--max-channels-per-iter",
        type=int,
        default=getattr(config, "TELEGRAM_MAX_CHANNELS_PER_ITER", 50),
        help="Сколько каналов обрабатывать за одну итерацию",
    )
    parser.add_argument(
        "--fetch-workers",
        type=int,
        default=getattr(config, "TELEGRAM_FETCH_WORKERS", 5),
        help="Количество асинхронных воркеров Telethon",
    )
    parser.add_argument(
        "--messages-per-channel",
        type=int,
        default=getattr(
            config,
            "TELEGRAM_MESSAGES_PER_CHANNEL",
            getattr(config, "TELEGRAM_FETCH_LIMIT", 30),
        ),
        help="Сколько сообщений загружать из каждого канала",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=getattr(config, "TELEGRAM_RATE_LIMIT", 25.0),
        help="Глобальный лимит операций Telegram (запросов в секунду)",
    )
    parser.add_argument(
        "--flood-sleep-threshold",
        type=int,
        default=getattr(config, "TELETHON_FLOOD_SLEEP_THRESHOLD", 30),
        help="Порог авто-ожидания FloodWait для Telethon (сек)",
    )
    parser.add_argument("--only-raw", action="store_true", help="Запустить только RAW-поток")
    parser.add_argument("--no-raw", action="store_true", help="Пропустить RAW-поток")
    args = parser.parse_args()

    config.TELEGRAM_MAX_CHANNELS_PER_ITER = max(1, int(args.max_channels_per_iter))
    config.TELEGRAM_FETCH_WORKERS = max(1, int(args.fetch_workers))
    config.TELEGRAM_FETCH_LIMIT = max(1, int(args.messages_per_channel))
    config.TELEGRAM_MESSAGES_PER_CHANNEL = config.TELEGRAM_FETCH_LIMIT
    config.TELEGRAM_RATE_LIMIT = max(0.1, float(args.rate))
    config.TELETHON_FLOOD_SLEEP_THRESHOLD = max(0, int(args.flood_sleep_threshold))

    configure_rate_limiter(config.TELEGRAM_RATE_LIMIT)

    if args.dry_run:
        os.environ["DRY_RUN"] = "1"
        setattr(config, "DRY_RUN", True)
        if getattr(config, "ENABLE_MODERATION", False):
            review_chat = str(getattr(config, "REVIEW_CHAT_ID", "")).strip()
            if not review_chat or review_chat == "@your_review_channel":
                logger.info(
                    "[DRY-RUN] Модерация отключена: REVIEW_CHAT_ID не задан"
                )
                setattr(config, "ENABLE_MODERATION", False)
        if getattr(config, "RAW_STREAM_ENABLED", False):
            raw_chat = str(getattr(config, "RAW_REVIEW_CHAT_ID", "")).strip()
            if not raw_chat:
                logger.info(
                    "[DRY-RUN] RAW-поток отключен: RAW_REVIEW_CHAT_ID не задан"
                )
                setattr(config, "RAW_STREAM_ENABLED", False)

    if args.only_raw and args.no_raw:
        parser.error("Нельзя использовать одновременно --only-raw и --no-raw")

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

    raw_mode = "only" if args.only_raw else "skip" if args.no_raw else "auto"

    if not args.loop:
        if args.once:
            logger.info("Запрошен одиночный прогон (--once)")
        summary = run_once(conn, raw_mode=raw_mode)
        if args.once and args.dry_run:
            logger.info(
                "[DRY-RUN] pipeline counters: in=%d after_fetch=%d after_filters=%d after_dedup=%d after_moderation=%d to_publish=%d",
                summary.stages["in"],
                summary.stages["after_fetch"],
                summary.stages["after_filters"],
                summary.stages["after_dedup"],
                summary.stages["after_moderation"],
                summary.stages["to_publish"],
            )
        return 0

    logger.info(
        "Старт бесконечного цикла обработки (LOOP_DELAY_SECS=%d)",
        config.LOOP_DELAY_SECS,
    )
    print("START LOOP")
    sys.stdout.flush()
    logger.info("START LOOP")
    while True:
        print("BEGIN ITERATION", time.time())
        sys.stdout.flush()
        logger.info("BEGIN ITERATION")
        logger.info("===> Итерация старта")
        try:
            run_once(conn, raw_mode=raw_mode)
            print("END run_once", time.time())
            sys.stdout.flush()
            logger.info("END run_once")
            logger.info("===> Итерация завершена, sleep")
            time.sleep(config.LOOP_DELAY_SECS)
            print("SLEEP END", time.time())
            sys.stdout.flush()
            logger.info("SLEEP END")
        except KeyboardInterrupt:
            print("KeyboardInterrupt detected", time.time())
            sys.stdout.flush()
            logger.warning("Остановка по Ctrl+C")
            break
        except Exception as ex:
            exc_type = type(ex).__name__
            print(f"Exception caught: {exc_type}: {ex}")
            traceback.print_exc(file=sys.stdout)
            sys.stdout.flush()
            logger.exception("Ошибка на итерации цикла (%s): %s", exc_type, ex)
            time.sleep(15)
            print("SLEEP END", time.time())
            sys.stdout.flush()
            logger.info("SLEEP END")
        except BaseException as ex:
            exc_type = type(ex).__name__
            print(f"BaseException caught: {exc_type}: {ex}")
            traceback.print_exc(file=sys.stdout)
            sys.stdout.flush()
            logger.exception("FATAL BaseException (%s): %s", exc_type, ex)
            time.sleep(15)
            print("SLEEP END", time.time())
            sys.stdout.flush()
            logger.info("SLEEP END")

    logger.info("Вышли из while True")
    print("EXIT while True", time.time())
    sys.stdout.flush()
    logger.info("EXIT while True")

    stop_event.set()
    if updates_thread is not None:
        updates_thread.join(timeout=5)
    return 0

if __name__ == "__main__":
    sys.exit(main())

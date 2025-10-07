from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
import datetime as dt
import logging
import json
import time
from dataclasses import dataclass
from pathlib import Path
import sys
import threading
from typing import Any, Dict, Iterable, Iterator, List, Optional

from telethon.tl.custom.message import Message
from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto

try:  # pragma: no cover - optional import for package mode
    import config
except ImportError:  # pragma: no cover - direct execution
    import config  # type: ignore

from rate_limiter import get_global_bucket
from teleapi_client import fetch_bulk_channels, get_mtproto_client, normalize_telegram_link
from telegram_web import fetch_latest as web_fetch_latest
from webwork.utils.formatting import TG_TEXT_LIMIT, safe_format

log = logging.getLogger(__name__)


@dataclass(slots=True)
class TelegramPost:
    title: str
    text: str
    url: str
    media: Optional[str]
    source: str
    ts: str
    dedup_key: str
    alias: str

    def as_item(self) -> Dict[str, Any]:
        payload = {
            "title": self.title,
            "text": self.text,
            "url": self.url,
            "media": self.media,
            "source": self.source,
            "ts": self.ts,
            "dedup_key": self.dedup_key,
            # Backwards compatibility for the main pipeline expecting these keys
            "content": self.text,
            "summary": "",
            "guid": self.dedup_key,
            "published_at": self.ts,
            "source_id": f"tg:{self.alias}",
        }
        return payload


@dataclass(slots=True)
class FetchOptions:
    max_channels_per_iter: int = 50
    fetch_workers: int = 5
    messages_per_channel: int = 50
    rate: float = 25.0
    flood_sleep_threshold: int = 30
    timeout_seconds: Optional[float] = 30.0


class TelegramFetchTimeoutError(RuntimeError):
    """Raised when fetching messages from Telegram exceeds the allotted time."""


def _state_path() -> Path:
    path = Path(getattr(config, "PIPELINE_STATE_PATH", "var/state.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_state() -> Dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Telegram: не удалось прочитать состояние %s: %s", path, exc)
        return {}


def _save_state(data: Dict[str, Any]) -> None:
    path = _state_path()
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        log.warning("Telegram: не удалось сохранить состояние %s: %s", path, exc)


def _state_key(links_file: str) -> str:
    try:
        resolved = str(Path(links_file).resolve())
    except Exception:
        resolved = str(Path(links_file))
    return f"telegram::{resolved}"


def _load_chunk_index(state_key: str, chunk_count: int) -> int:
    if chunk_count <= 0:
        return 0
    state = _load_state()
    telegram_state = state.get("telegram", {}) if isinstance(state, dict) else {}
    entry = telegram_state.get(state_key, {}) if isinstance(telegram_state, dict) else {}
    try:
        pointer = int(entry.get("next_index", 0))
    except (TypeError, ValueError):
        pointer = 0
    if pointer < 0 or pointer >= chunk_count:
        pointer = 0
    return pointer


def _store_chunk_index(state_key: str, chunk_count: int, next_index: int) -> None:
    state = _load_state()
    if not isinstance(state, dict):
        state = {}
    telegram_state = state.setdefault("telegram", {})
    if not isinstance(telegram_state, dict):
        telegram_state = {}
        state["telegram"] = telegram_state
    telegram_state[state_key] = {
        "next_index": int(max(0, next_index)),
        "total_chunks": int(max(1, chunk_count)) if chunk_count else 0,
        "updated_at": int(time.time()),
    }
    _save_state(state)


def _enforce_limit(text: str, limit: int) -> str:
    payload = (text or "").strip()
    formatted = safe_format(payload, getattr(config, "TELEGRAM_PARSE_MODE", "HTML"))
    if len(formatted) <= limit:
        return payload
    return payload[: max(0, limit - 1)].rstrip() + "…"


def _message_to_post(message: Message, alias: str) -> TelegramPost:
    text = (message.message or "").strip()
    title = text.split("\n", 1)[0] if text else f"Сообщение {message.id}"
    url = getattr(message, "link", None) or f"https://t.me/{alias}/{message.id}"
    published = ""
    if message.date:
        try:
            published = message.date.astimezone(dt.timezone.utc).isoformat()
        except Exception:  # pragma: no cover - defensive fallback
            try:
                published = message.date.isoformat()
            except Exception:
                published = ""
    media_type: Optional[str] = None
    if isinstance(message.media, MessageMediaPhoto):
        media_type = "photo"
    elif isinstance(message.media, MessageMediaDocument):
        if getattr(message.media, "video", None) or getattr(message, "video", None):
            media_type = "video"
        else:
            media_type = "document"
    trimmed_text = _enforce_limit(text, TG_TEXT_LIMIT)
    post = TelegramPost(
        title=_enforce_limit(title, TG_TEXT_LIMIT),
        text=trimmed_text,
        url=url,
        media=media_type,
        source=f"t.me/{alias}",
        ts=published,
        dedup_key=f"tg:{alias}:{message.id}",
        alias=alias,
    )
    return post


def _web_item_to_post(item: Dict[str, Any]) -> TelegramPost:
    alias = normalize_telegram_link(item.get("tg_alias") or item.get("source") or "") or ""
    title = (item.get("title") or "").strip()
    text = (item.get("content") or "").strip()
    published = (item.get("published_at") or "").strip()
    url = (item.get("url") or "").strip()
    if alias:
        dedup_key = f"tg:{alias}:{item.get('tg_msg_id') or ''}".rstrip(":")
    else:
        dedup_key = item.get("guid") or (item.get("url") or "")
    post = TelegramPost(
        title=_enforce_limit(title, TG_TEXT_LIMIT),
        text=_enforce_limit(text, TG_TEXT_LIMIT),
        url=url,
        media=None,
        source=f"t.me/{alias}" if alias else (item.get("source") or ""),
        ts=published,
        dedup_key=str(dedup_key),
        alias=alias,
    )
    return post


def _load_aliases(path: str) -> List[str]:
    file_path = Path(path)
    if not file_path.exists():
        log.warning("Telegram: файл со ссылками не найден: %s", file_path)
        return []
    aliases: List[str] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        alias = normalize_telegram_link(stripped)
        if alias:
            aliases.append(alias)
    unique_aliases = sorted(dict.fromkeys(aliases))
    log.info("Telegram: загружено %d каналов", len(unique_aliases))
    return unique_aliases


async def _fetch_mtproto_async(
    aliases: Iterable[str],
    limit: int,
    *,
    options: Optional[FetchOptions] = None,
) -> List[TelegramPost]:
    alias_list = list(aliases)
    log.info(
        "fetch_mtproto_async:start alias_count=%s limit=%s options=%s",
        len(alias_list),
        limit,
        options,
    )
    api_id = getattr(config, "TELETHON_API_ID", 0)
    api_hash = getattr(config, "TELETHON_API_HASH", "")
    session = getattr(config, "TELETHON_SESSION_NAME", "webwork_telethon")
    if api_id <= 0 or not api_hash:
        raise RuntimeError("TELETHON_API_ID/TELETHON_API_HASH не заданы")
    flood_threshold = None
    if options is not None:
        flood_threshold = options.flood_sleep_threshold
    client = get_mtproto_client(
        api_id,
        api_hash,
        session,
        flood_sleep_threshold=flood_threshold,
    )
    log.debug("fetch_mtproto_async: Telethon client created session=%s", session)
    session_obj = getattr(client, "session", None)
    session_filename = getattr(session_obj, "filename", None)
    if isinstance(session_filename, str) and session_filename.strip():
        raw_path = Path(session_filename).expanduser()
        if not raw_path.is_absolute():
            raw_path = Path.cwd() / raw_path
        if not raw_path.exists():
            message = (
                "Не найден файл сессии Telethon: "
                f"{raw_path}. Завершите интерактивный вход один раз или "
                "передайте путь к готовому .session через TELETHON_SESSION_NAME."
            )
            log.error("fetch_mtproto_async: %s", message)
            raise RuntimeError(message)
    concurrency = options.fetch_workers if options else 5
    bucket = get_global_bucket((options.rate if options else 25.0) or 25.0)
    fetch_timeout = None
    if options and options.timeout_seconds and options.timeout_seconds > 0:
        fetch_timeout = float(options.timeout_seconds)
    messages_by_alias: Dict[str, List[Message]] = {}
    try:
        async with client:
            log.debug(
                "fetch_mtproto_async: client session entered concurrency=%s timeout=%s",
                concurrency,
                fetch_timeout,
            )
            try:
                coro = fetch_bulk_channels(
                    client,
                    alias_list,
                    limit,
                    concurrency=concurrency,
                    bucket=bucket,
                )
                if fetch_timeout is not None:
                    log.debug(
                        "fetch_mtproto_async: awaiting fetch_bulk_channels with timeout=%s",
                        fetch_timeout,
                    )
                    messages_by_alias = await asyncio.wait_for(coro, timeout=fetch_timeout)
                    log.debug(
                        "fetch_mtproto_async: fetch_bulk_channels completed within timeout"
                    )
                else:
                    log.debug(
                        "fetch_mtproto_async: awaiting fetch_bulk_channels without explicit timeout"
                    )
                    messages_by_alias = await coro
                    log.debug("fetch_mtproto_async: fetch_bulk_channels completed without timeout")
                log.info(
                    "fetch_mtproto_async: fetch completed alias_count=%s",
                    len(messages_by_alias),
                )
            except asyncio.TimeoutError as exc:
                log.warning(
                    "fetch_mtproto_async: timeout after %.2fs while fetching aliases",
                    fetch_timeout or 0,
                )
                raise TelegramFetchTimeoutError(
                    f"Telegram MTProto fetch timed out after {fetch_timeout:.1f} seconds"
                    if fetch_timeout
                    else "Telegram MTProto fetch timed out"
                ) from exc
            except Exception as exc:
                log.exception(
                    "fetch_mtproto_async: exception during fetch type=%s error=%s",
                    type(exc).__name__,
                    exc,
                )
                raise
            except BaseException as exc:
                log.critical(
                    "fetch_mtproto_async: base-exception during fetch type=%s error=%s",
                    type(exc).__name__,
                    exc,
                )
                raise
            finally:
                log.debug("fetch_mtproto_async: leaving fetch_bulk_channels await")
        log.debug("fetch_mtproto_async: client session exited cleanly")
    except Exception as exc:
        log.exception(
            "fetch_mtproto_async: caught exception type=%s error=%s",
            type(exc).__name__,
            exc,
        )
        raise
    except BaseException as exc:
        log.critical(
            "fetch_mtproto_async: caught base-exception type=%s error=%s",
            type(exc).__name__,
            exc,
        )
        raise
    finally:
        log.info(
            "fetch_mtproto_async:finish alias_count=%s limit=%s",
            len(alias_list),
            limit,
        )
    posts: List[TelegramPost] = []
    for alias, messages in messages_by_alias.items():
        for message in messages:
            posts.append(_message_to_post(message, alias))
    return posts


def _chunk_aliases(aliases: List[str], chunk_size: int) -> List[List[str]]:
    if chunk_size <= 0:
        return [aliases]
    result: List[List[str]] = []
    for idx in range(0, len(aliases), chunk_size):
        result.append(aliases[idx : idx + chunk_size])
    return result or [aliases]


def _fetch_from_telegram_sync(
    mode: str,
    links_file: str,
    limit: int,
    opts: FetchOptions,
) -> List[Dict[str, Any]]:
    log.info(
        "fetch_from_telegram_sync:start mode=%s links_file=%s limit=%s opts=%s",
        mode,
        links_file,
        limit,
        opts,
    )
    log.debug("fetch_from_telegram_sync: loading aliases from %s", links_file)
    aliases = _load_aliases(links_file)
    log.debug("fetch_from_telegram_sync: loaded %s aliases", len(aliases))
    if not aliases:
        log.info("fetch_from_telegram_sync:no aliases loaded, returning empty list")
        return []
    chunk_size = max(1, min(opts.max_channels_per_iter, len(aliases)))
    log.debug(
        "fetch_from_telegram_sync: chunking aliases chunk_size=%s max_channels=%s",
        chunk_size,
        opts.max_channels_per_iter,
    )
    chunks = _chunk_aliases(aliases, chunk_size)
    state_key = _state_key(links_file)
    chunk_index = _load_chunk_index(state_key, len(chunks))
    log.debug(
        "fetch_from_telegram_sync: resolved chunk_index=%s total_chunks=%s",
        chunk_index,
        len(chunks),
    )
    current_chunk = chunks[chunk_index]
    log.info(
        "Telegram: обработка чанка %s/%s (%s каналов)",
        chunk_index + 1,
        len(chunks),
        len(current_chunk),
    )
    mode_normalized = (mode or "mtproto").strip().lower()
    msg_limit = opts.messages_per_channel or limit
    posts: List[TelegramPost]
    if mode_normalized == "mtproto":
        hard_timeout = None
        if opts.timeout_seconds and opts.timeout_seconds > 0:
            hard_timeout = float(opts.timeout_seconds)
        log.debug(
            "fetch_from_telegram_sync: creating event loop hard_timeout=%s", hard_timeout
        )
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            log.debug("fetch_from_telegram_sync: entering loop.run_until_complete")
            coroutine = _fetch_mtproto_async(current_chunk, msg_limit, options=opts)
            if hard_timeout is not None:
                log.debug(
                    "fetch_from_telegram_sync: applying asyncio.wait_for hard_timeout=%s",
                    hard_timeout,
                )
                coroutine = asyncio.wait_for(coroutine, timeout=hard_timeout)
            start_time = time.time()
            try:
                posts = loop.run_until_complete(coroutine)
                log.debug(
                    "fetch_from_telegram_sync: loop.run_until_complete finished elapsed=%.2fs",
                    time.time() - start_time,
                )
            except asyncio.TimeoutError as exc:
                log.warning(
                    "fetch_from_telegram_sync: hard timeout after %.2fs waiting for async fetch",
                    hard_timeout or 0.0,
                )
                raise TelegramFetchTimeoutError(
                    f"Telegram fetch hard timeout after {hard_timeout:.1f} seconds"
                ) from exc
            except Exception as exc:
                log.exception(
                    "fetch_from_telegram_sync: run_until_complete failed type=%s error=%s",
                    type(exc).__name__,
                    exc,
                )
                raise
            finally:
                pending_tasks = [
                    task for task in asyncio.all_tasks(loop) if not task.done()
                ]
                if pending_tasks:
                    log.warning(
                        "fetch_from_telegram_sync: cancelling %s pending tasks=%s",
                        len(pending_tasks),
                        [repr(task) for task in pending_tasks],
                    )
                    for task in pending_tasks:
                        task.cancel()
                    try:
                        loop.run_until_complete(
                            asyncio.gather(*pending_tasks, return_exceptions=True)
                        )
                        log.debug(
                            "fetch_from_telegram_sync: pending tasks drained successfully"
                        )
                    except Exception as cleanup_exc:
                        log.exception(
                            "fetch_from_telegram_sync: error draining pending tasks type=%s error=%s",
                            type(cleanup_exc).__name__,
                            cleanup_exc,
                        )
        finally:
            try:
                log.debug("fetch_from_telegram_sync: shutting down async generators")
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception as exc:  # pragma: no cover - cleanup guard
                log.exception(
                    "fetch_from_telegram_sync: shutdown_asyncgens failed type=%s error=%s",
                    type(exc).__name__,
                    exc,
                )
            finally:
                asyncio.set_event_loop(None)
                try:
                    log.debug("fetch_from_telegram_sync: closing event loop")
                    loop.close()
                except Exception as exc:  # pragma: no cover - cleanup guard
                    log.exception(
                        "fetch_from_telegram_sync: loop.close failed type=%s error=%s",
                        type(exc).__name__,
                        exc,
                    )
    elif mode_normalized == "web":
        posts = []
        bucket = get_global_bucket(opts.rate)
        web_timeout = None
        if opts.timeout_seconds and opts.timeout_seconds > 0:
            web_timeout = float(opts.timeout_seconds)
        log.debug(
            "fetch_from_telegram_sync:web mode start chunk_size=%s web_timeout=%s",
            len(current_chunk),
            web_timeout,
        )
        with ThreadPoolExecutor(max_workers=1) as web_executor:
            for alias in current_chunk:
                log.debug("fetch_from_telegram_sync:web fetching alias=%s", alias)
                future = None
                try:
                    bucket.consume()
                    log.debug("fetch_from_telegram_sync:web bucket consumed alias=%s", alias)
                    future = web_executor.submit(web_fetch_latest, alias, limit=limit)
                    if web_timeout is not None:
                        log.debug(
                            "fetch_from_telegram_sync:web awaiting result alias=%s timeout=%s",
                            alias,
                            web_timeout,
                        )
                        items = future.result(timeout=web_timeout)
                    else:
                        log.debug(
                            "fetch_from_telegram_sync:web awaiting result alias=%s without timeout",
                            alias,
                        )
                        items = future.result()
                    log.debug(
                        "fetch_from_telegram_sync:web fetch completed alias=%s items=%s",
                        alias,
                        len(items),
                    )
                except FuturesTimeoutError:
                    log.warning(
                        "fetch_from_telegram_sync:web fetch timeout alias=%s after %.2fs",
                        alias,
                        web_timeout or 0.0,
                    )
                    if future is not None:
                        future.cancel()
                    continue
                except Exception as exc:  # pragma: no cover - network errors
                    log.warning(
                        "fetch_from_telegram_sync:web fetch error alias=%s type=%s error=%s",
                        alias,
                        type(exc).__name__,
                        exc,
                    )
                    if future is not None and not future.done():
                        future.cancel()
                    continue
                for item in items:
                    posts.append(_web_item_to_post(item))
        log.debug(
            "fetch_from_telegram_sync:web mode finished total_posts=%s", len(posts)
        )
    else:
        raise ValueError(f"Unknown telegram mode: {mode}")
    _store_chunk_index(state_key, len(chunks), (chunk_index + 1) % len(chunks))
    log.info("Telegram: получено %d сообщений (mode=%s)", len(posts), mode_normalized)
    log.info(
        "fetch_from_telegram_sync:return result_count=%s mode=%s",
        len(posts),
        mode_normalized,
    )
    return [post.as_item() for post in posts]


def fetch_from_telegram(
    mode: str,
    links_file: str,
    limit: int,
    *,
    options: Optional[FetchOptions] = None,
    timeout: Optional[float] = None,
) -> List[Dict[str, Any]]:
    log.info(
        "fetch_from_telegram:start mode=%s links_file=%s limit=%s timeout=%s options=%s",
        mode,
        links_file,
        limit,
        timeout,
        options,
    )
    log.debug(
        "fetch_from_telegram:entered thread=%s", threading.current_thread().name
    )
    opts = options or FetchOptions()
    effective_timeout = timeout
    if effective_timeout is None:
        effective_timeout = opts.timeout_seconds
    if effective_timeout is not None and effective_timeout <= 0:
        effective_timeout = None

    def _call() -> List[Dict[str, Any]]:
        thread_name = threading.current_thread().name
        log.debug("fetch_from_telegram:_call start thread=%s", thread_name)
        try:
            log.debug(
                "fetch_from_telegram:_call invoking _fetch_from_telegram_sync for %s",
                thread_name,
            )
            result = _fetch_from_telegram_sync(mode, links_file, limit, opts)
            log.debug(
                "fetch_from_telegram:_call result obtained thread=%s result_count=%s",
                thread_name,
                len(result),
            )
            log.info(
                "fetch_from_telegram:_call completed thread=%s result_count=%s",
                thread_name,
                len(result),
            )
            return result
        except Exception as exc:
            log.exception(
                "fetch_from_telegram:_call exception thread=%s type=%s error=%s",
                thread_name,
                type(exc).__name__,
                exc,
            )
            raise
        except BaseException as exc:
            log.critical(
                "fetch_from_telegram:_call base-exception thread=%s type=%s error=%s",
                thread_name,
                type(exc).__name__,
                exc,
            )
            raise
        finally:
            log.debug("fetch_from_telegram:_call finally thread=%s", thread_name)

    try:
        if effective_timeout is None:
            log.debug("fetch_from_telegram: executing synchronously without timeout")
            result = _call()
            log.info(
                "fetch_from_telegram:return without timeout result_count=%s",
                len(result),
            )
            log.debug(
                "fetch_from_telegram: returning synchronously thread=%s", 
                threading.current_thread().name,
            )
            return result

        completion_event = threading.Event()
        worker_result: Dict[str, List[Dict[str, Any]]] = {}
        worker_exc: Dict[str, Any] = {}

        def _worker() -> None:
            worker_thread = threading.current_thread().name
            log.debug("fetch_from_telegram: worker start thread=%s", worker_thread)
            try:
                result = _call()
                worker_result["value"] = result
                log.debug(
                    "fetch_from_telegram: worker obtained result thread=%s result_count=%s",
                    worker_thread,
                    len(result),
                )
            except BaseException as exc:
                worker_exc["exc_info"] = sys.exc_info()
                log.debug(
                    "fetch_from_telegram: worker captured exception thread=%s type=%s",
                    worker_thread,
                    type(exc).__name__,
                )
            finally:
                log.debug(
                    "fetch_from_telegram: worker signalling completion thread=%s",
                    worker_thread,
                )
                completion_event.set()

        worker_thread = threading.Thread(
            target=_worker,
            name="fetch_from_telegram_worker",
            daemon=True,
        )
        log.debug(
            "fetch_from_telegram: starting worker thread=%s timeout=%.2f",
            worker_thread.name,
            effective_timeout,
        )
        worker_thread.start()
        finished = completion_event.wait(timeout=effective_timeout)
        log.debug(
            "fetch_from_telegram: wait finished=%s thread_alive=%s",
            finished,
            worker_thread.is_alive(),
        )
        if not finished:
            log.warning(
                "fetch_from_telegram: timeout waiting for worker after %.2fs", 
                effective_timeout,
            )
            raise TelegramFetchTimeoutError(
                f"Telegram fetch timed out after {effective_timeout:.1f} seconds"
            )

        worker_thread.join(timeout=1.0)
        if worker_thread.is_alive():
            log.warning(
                "fetch_from_telegram: worker thread still alive after join thread=%s",
                worker_thread.name,
            )
        else:
            log.debug(
                "fetch_from_telegram: worker thread joined thread=%s",
                worker_thread.name,
            )

        if "exc_info" in worker_exc:
            exc_type, exc_value, exc_tb = worker_exc["exc_info"]
            log.debug(
                "fetch_from_telegram: re-raising worker exception type=%s",
                exc_type.__name__ if exc_type else "unknown",
            )
            if exc_value is not None and exc_tb is not None:
                raise exc_value.with_traceback(exc_tb)
            if exc_value is not None:
                raise exc_value
            raise RuntimeError("Unknown exception in fetch_from_telegram worker")

        result = worker_result.get("value", [])
        log.info(
            "fetch_from_telegram:return with timeout result_count=%s",
            len(result),
        )
        log.debug(
            "fetch_from_telegram: returning from timed execution thread=%s", 
            threading.current_thread().name,
        )
        return result
    except Exception as exc:
        log.exception(
            "fetch_from_telegram: caught exception type=%s error=%s",
            type(exc).__name__,
            exc,
        )
        raise
    except BaseException as exc:
        log.critical(
            "fetch_from_telegram: caught base-exception type=%s error=%s",
            type(exc).__name__,
            exc,
        )
        raise
    finally:
        log.info(
            "fetch_from_telegram:finish mode=%s links_file=%s limit=%s timeout=%s",
            mode,
            links_file,
            limit,
            effective_timeout,
        )


def fetch_posts_iterator(mode: str, links_file: str, limit: int) -> Iterator[Dict[str, Any]]:
    for item in fetch_from_telegram(mode, links_file, limit):
        yield item

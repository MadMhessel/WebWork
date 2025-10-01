from __future__ import annotations

# import-shim: allow running as a script (no package parent)
if __name__ == "__main__" or __package__ is None:
    import os
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
# end of shim

import logging
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

import config

logger = logging.getLogger(__name__)

_ALIAS_RE = re.compile(r"(?:https?://)?t\.me/(?:s/)?(@?[\w\d_+\-]+)")


def _normalize_alias(value: str) -> Optional[str]:
    if not value:
        return None
    match = _ALIAS_RE.search(value.strip())
    if not match:
        return None
    alias = match.group(1).lstrip("@")
    return alias.lower()


def _load_aliases(path: Path) -> List[str]:
    if not path.exists():
        logger.warning("TG-WEB: файл со списком каналов не найден: %s", path)
        return []
    aliases: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        alias = _normalize_alias(stripped)
        if alias:
            aliases.append(alias)
    unique_aliases = sorted(dict.fromkeys(aliases))
    logger.info("TG-WEB: загружено %d каналов", len(unique_aliases))
    return unique_aliases


def fetch_from_file(path: str) -> Iterator[Dict[str, object]]:
    """Читает список каналов и выдаёт элементы Telegram."""

    aliases = _load_aliases(Path(path))
    if not aliases:
        return

    session = requests.Session()
    limit = int(getattr(config, "TELEGRAM_FETCH_LIMIT", 30))
    for idx, alias in enumerate(aliases):
        if idx > 0:
            pause = random.uniform(6.0, 10.0)
            logger.debug("TG-WEB: пауза %.1f сек перед каналом %s", pause, alias)
            time.sleep(pause)
        try:
            for item in fetch_latest(alias, session=session, limit=limit):
                yield item
        except Exception as exc:  # pragma: no cover - логирование для продакшена
            logger.exception("TG-WEB: ошибка обработки %s: %s", alias, exc)


def fetch_latest(
    alias: str,
    *,
    session: Optional[requests.Session] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, object]]:
    """Скачивает публичную страницу t.me/s/<alias> и возвращает последние посты."""

    session = session or requests.Session()
    url = f"https://t.me/s/{alias}"
    attempts = 0
    max_attempts = 5
    backoff_base = 3.0
    while True:
        attempts += 1
        try:
            response = session.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121 Safari/537.36"
                    ),
                    "Accept-Language": "ru-RU,ru;q=0.9",
                    "Cache-Control": "no-cache",
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            if attempts >= max_attempts:
                logger.warning("TG-WEB: не удалось получить %s: %s", url, exc)
                return []
            wait = backoff_base * (2 ** (attempts - 1)) + random.uniform(0.5, 1.5)
            logger.warning("TG-WEB: ошибка запроса %s, повтор через %.1f сек", alias, wait)
            time.sleep(wait)
            continue

        if response.status_code == 200:
            html = response.text
            break

        if response.status_code in {429} or 500 <= response.status_code < 600:
            if attempts >= max_attempts:
                logger.warning(
                    "TG-WEB: превышено число попыток для %s, код %s", alias, response.status_code
                )
                return []
            wait = backoff_base * (2 ** (attempts - 1)) + random.uniform(1.0, 3.0)
            logger.warning(
                "TG-WEB: код %s при обращении к %s, повтор через %.1f сек",
                response.status_code,
                alias,
                wait,
            )
            time.sleep(wait)
            continue

        if response.status_code == 404:
            logger.warning("TG-WEB: канал %s не найден (404)", alias)
            return []

        response.raise_for_status()

    soup = BeautifulSoup(html, "html.parser")
    max_items = limit or int(getattr(config, "TELEGRAM_FETCH_LIMIT", 30))
    items: List[Dict[str, object]] = []
    for wrap in soup.select(".tgme_widget_message_wrap"):
        link_el = wrap.select_one("a.tgme_widget_message_date")
        if not link_el:
            continue
        link = link_el.get("href", "").strip()
        message_id = ""
        canonical_url = link
        alias_clean = alias
        if link:
            parsed = urlparse(link)
            parts = [p for p in parsed.path.split("/") if p]
            alias_candidate = alias
            msg_part = ""
            if parts:
                if parts[0] == "s" and len(parts) >= 2:
                    alias_candidate = parts[1]
                    if len(parts) >= 3:
                        msg_part = parts[2]
                else:
                    alias_candidate = parts[0]
                    if len(parts) >= 2:
                        msg_part = parts[1]
            alias_clean = alias_candidate.strip("@") or alias
            msg_part = (msg_part or "").split("?")[0]
            message_id = msg_part
            if message_id:
                canonical_url = f"https://t.me/{alias_clean}/{message_id}"
            else:
                canonical_url = f"https://t.me/{alias_clean}"
        time_el = link_el.select_one("time")
        published = ""
        if time_el is not None:
            raw_dt = time_el.get("datetime", "").strip()
            if raw_dt:
                try:
                    dt_obj = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
                    dt_utc = dt_obj.astimezone(timezone.utc)
                    published = dt_utc.isoformat()
                except ValueError:
                    published = raw_dt

        text_el = wrap.select_one(".tgme_widget_message_text")
        content = ""
        if text_el is not None:
            content = text_el.get_text("\n", strip=True)

        title = ""
        if content:
            title = content.split("\n", 1)[0]
        if not title:
            title = f"Сообщение {message_id or alias}"

        items.append(
            {
                "source": f"t.me/{alias_clean}",
                "source_id": f"tg:{alias_clean}",
                "guid": f"tg:{alias_clean}:{message_id}" if message_id else canonical_url,
                "url": canonical_url or link,
                "title": title,
                "content": content,
                "published_at": published,
                "summary": "",
                "source_domain": "t.me",
                "trust_level": 1,
                "tg_alias": alias_clean,
                "tg_msg_id": int(message_id) if message_id.isdigit() else None,
            }
        )

        if max_items and len(items) >= max_items:
            break

    logger.info("TG-WEB: получено %d постов из %s", len(items), alias)
    return items

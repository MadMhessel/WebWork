from __future__ import annotations

# import-shim: allow running as a script (no package parent)
if __name__ == "__main__" or __package__ is None:
    import os
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
# end of shim

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

import hashlib
import logging
import re

import yaml

_DEFAULTS_CACHE: Dict[str, Any] | None = None
_SOURCES_CACHE: List[Dict[str, Any]] | None = None
_log = logging.getLogger("webwork.app.sources")

import config

VERSION_REQUIRED = 2
_RUBRICS = {"kazusy", "objects", "persons"}


def _load_yaml() -> Dict[str, Any]:
    path = Path(__file__).resolve().with_name("sources_nn.yaml")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if int(data.get("version", 0)) != VERSION_REQUIRED:
        raise ValueError(
            f"Неверная версия конфигурации: {data.get('version')}, ожидается {VERSION_REQUIRED}"
        )
    return data


def _normalize_domain(value: str | None) -> str:
    """Return normalized domain for URLs/domains from configuration."""

    if not value:
        return ""

    domain = value.strip()
    if not domain:
        return ""

    parsed = None
    low = domain.lower()
    if low.startswith("http://") or low.startswith("https://"):
        parsed = urlparse(domain)
    elif low.startswith("//"):
        parsed = urlparse("http:" + domain)
    elif "/" in low or "?" in low or "#" in low:
        parsed = urlparse("http://" + domain)

    if parsed:
        host = parsed.hostname or ""
    else:
        host = domain

    host = host.strip().lower()
    if host.startswith("www."):
        host = host[4:]

    if not host:
        return ""

    try:
        host = host.encode("idna").decode("ascii")
    except Exception:
        pass

    return host


_slug_re = re.compile(r"[^a-z0-9]+")


def _merge_defaults(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    defaults = deepcopy(data.get("defaults") or {})
    sources_raw = data.get("sources") or []
    result: List[Dict[str, Any]] = []
    for entry in sources_raw:
        merged = deepcopy(defaults)
        merged.update(entry or {})

        url = (merged.get("url") or "").strip()
        if not url:
            raise ValueError("Источник без url")

        merged["url"] = url

        stype = str(merged.get("type") or "").lower()
        if stype not in {"rss", "html"}:
            raise ValueError(f"Неподдерживаемый type={stype} у {merged.get('name') or url}")
        merged["type"] = stype

        try:
            tl = int(merged.get("trust_level", 1))
        except (TypeError, ValueError):
            raise ValueError(f"Некорректный trust_level у {merged.get('name') or url}")
        if tl not in (1, 2, 3):
            raise ValueError(f"trust_level={tl} вне диапазона у {merged.get('name') or url}")
        merged["trust_level"] = tl

        rubrics_raw = merged.get("rubrics_allowed")
        if rubrics_raw:
            rubrics = {str(r).strip() for r in rubrics_raw if str(r).strip()}
        else:
            rubrics = set(_RUBRICS)
        if not rubrics.issubset(_RUBRICS):
            raise ValueError(
                f"rubrics_allowed содержит неизвестные значения: {rubrics - _RUBRICS}"
            )
        merged["rubrics_allowed"] = sorted(rubrics)

        domain_hint = merged.get("source_domain") or merged.get("url")
        domain = _normalize_domain(domain_hint)
        merged["source_domain"] = domain
        merged.setdefault("enabled", True)
        merged.setdefault("rate_limit_per_minute", 12)
        merged.setdefault("retry", {"attempts": 2, "backoff_ms": 500})
        merged.setdefault("min_text_length", 200)
        merged.setdefault("enable_video_scrape", False)
        merged.setdefault("min_image_width", 900)
        if "name" not in merged:
            merged["name"] = domain or merged.get("url", "")

        if url.startswith(("http://", "https://")):
            parsed = urlparse(url)
        elif url.startswith("//"):
            parsed = urlparse("http:" + url)
        else:
            parsed = urlparse("http://" + url)
        if not domain:
            domain = _normalize_domain(parsed.hostname or "")
            if domain:
                merged["source_domain"] = domain
        base_domain = domain or "unknown"
        path_key = _slug_re.sub("-", (parsed.path or "/").strip("/").lower()).strip("-") or "root"
        base_id = f"{base_domain}:{path_key}"
        short = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
        merged.setdefault("id", f"{base_id}:{short}")
        result.append(merged)
    return result


# --- Telegram links support ---------------------------------------------------
_TG_RE = re.compile(r"(?i)^(?:https?://)?t\.me/(?:s/)?([A-Za-z0-9_+\-]+)$")


def _parse_telegram_slug(line: str) -> str | None:
    """Вернёт имя канала из строки-ссылки t.me, либо None. Пустые/комментарии игнорируются."""

    s = (line or "").strip()
    if not s or s.startswith("#"):
        return None
    match = _TG_RE.match(s)
    return match.group(1) if match else None


def _load_telegram_links(path: Path | None) -> list[str]:
    """Загрузить список имён каналов из текстового файла (по строке на ссылку)."""

    if not path or not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    slugs: list[str] = []
    seen: set[str] = set()
    for raw in lines:
        slug = _parse_telegram_slug(raw)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        slugs.append(slug)
    return slugs


def _entries_from_telegram(slugs: list[str], defaults: Dict[str, Any]) -> list[Dict[str, Any]]:
    """Сконструировать записи-источники для Telegram-просмотровых страниц."""

    out: list[Dict[str, Any]] = []
    for slug in slugs:
        url = f"https://t.me/s/{slug}"
        entry = deepcopy(defaults)
        entry.update(
            {
                "id": f"tg:{slug}",
                "name": f"TG · {slug}",
                "url": url,
                "type": "html",
                "source_domain": "t.me",
                "min_text_length": 80,
                "trust_level": 1,
                "rate_limit_per_minute": 4,
            }
        )
        out.append(entry)
    return out


def _build_sources() -> List[Dict[str, Any]]:
    global _DEFAULTS_CACHE
    data = _load_yaml()
    _DEFAULTS_CACHE = deepcopy(data.get("defaults") or {})
    base = _merge_defaults(data)

    links_file = getattr(config, "TELEGRAM_LINKS_FILE", "") or ""
    base_dir = Path(__file__).resolve().parent
    if links_file:
        lf = Path(links_file)
        tg_path = lf if lf.is_absolute() else (base_dir / lf)
    else:
        tg_path = None
    tg_slugs = _load_telegram_links(tg_path)
    dyn = _entries_from_telegram(tg_slugs, _DEFAULTS_CACHE or {})

    try:
        _log.info(
            "TG: загружено %d каналов из %s",
            len(tg_slugs),
            str(tg_path.resolve()) if tg_path else "<не задано>",
        )
    except Exception:
        pass

    merged: dict[str, Dict[str, Any]] = {}
    for src in base + dyn:
        sid = str(src.get("id") or src.get("name") or src.get("url"))
        if sid in merged:
            raise ValueError(f"Дубликат id источника: {sid}")
        merged[sid] = src
    return list(merged.values())


SOURCES_NN = _build_sources()

SOURCES_BY_DOMAIN: Dict[str, List[Dict[str, Any]]] = {}
for src in SOURCES_NN:
    dom = src.get("source_domain", "")
    if not dom:
        continue
    SOURCES_BY_DOMAIN.setdefault(dom, []).append(src)

SOURCES_BY_ID: Dict[str, Dict[str, Any]] = {}
for src in SOURCES_NN:
    key = str(src.get("id") or src.get("name"))
    if key in SOURCES_BY_ID:
        raise ValueError(f"Дубликат id источника: {key}")
    SOURCES_BY_ID[key] = src


def get_sources_by_domain(domain: str) -> List[Dict[str, Any]]:
    """Вернуть список источников по домену с учётом нормализации."""

    return SOURCES_BY_DOMAIN.get(_normalize_domain(domain), [])


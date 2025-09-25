from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

import hashlib
import re
import yaml

_DEFAULTS_CACHE: Dict[str, Any] | None = None
_SOURCES_CACHE: List[Dict[str, Any]] | None = None
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
    if not value:
        return ""
    domain = value.strip().lower()
    if domain.startswith("http"):
        parsed = urlparse(domain)
        domain = parsed.hostname or ""
    elif domain.startswith("//"):
        parsed = urlparse("http:" + domain)
        domain = parsed.hostname or ""
    if domain.startswith("www."):
        domain = domain[4:]
    try:
        domain = domain.encode("idna").decode("ascii")
    except Exception:
        pass
    return domain


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

        domain = _normalize_domain(merged.get("source_domain") or merged.get("url"))
        merged["source_domain"] = domain
        merged.setdefault("enabled", True)
        merged.setdefault("rate_limit_per_minute", 12)
        merged.setdefault("retry", {"attempts": 2, "backoff_ms": 500})
        merged.setdefault("min_text_length", 200)
        merged.setdefault("enable_video_scrape", False)
        merged.setdefault("min_image_width", 900)
        if "name" not in merged:
            merged["name"] = domain or merged.get("url", "")

        parsed = urlparse(url if url.startswith(("http://", "https://")) else ("http://" + url))
        path_key = _slug_re.sub("-", (parsed.path or "/").strip("/").lower()).strip("-") or "root"
        base_id = f"{domain}:{path_key}"
        short = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
        merged.setdefault("id", f"{base_id}:{short}")
        result.append(merged)
    return result


def _build_sources() -> List[Dict[str, Any]]:
    global _DEFAULTS_CACHE
    data = _load_yaml()
    _DEFAULTS_CACHE = deepcopy(data.get("defaults") or {})
    return _merge_defaults(data)


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


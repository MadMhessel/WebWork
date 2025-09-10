"""Fetch context images from open sources (Openverse/Wikimedia)."""

from __future__ import annotations

import logging
import re
import json
from typing import Dict, Optional

try:  # pragma: no cover - optional package structure
    from . import config, images, net
except Exception:  # pragma: no cover
    import config  # type: ignore
    import images  # type: ignore
    import net  # type: ignore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _licenses(cfg=config) -> set[str]:
    raw = getattr(cfg, "CONTEXT_LICENSES", "cc0,cc-by,cc-by-sa")
    return {s.strip().lower() for s in str(raw).split(",") if s.strip()}


def build_query(item: Dict, cfg=config) -> str:
    text = f"{item.get('title','')} {item.get('content','')}"
    tokens: list[str] = []
    patterns = [
        (r"мост|путепровод", "мост"),
        (r"дорог|трасс", "дорога"),
        (r"школ|садик|кампус", "школа"),
        (r"жк|дом|новострой", "новостройка"),
        (r"промзона|завод", "завод"),
        (r"набережн|сквер|парк", "парк"),
        (r"вокзал|метро|станц", "вокзал"),
    ]
    for rx, tok in patterns:
        if re.search(rx, text, re.I):
            tokens.append(tok)
    region_kw = list(getattr(cfg, "REGION_KEYWORDS", []))
    regions = [getattr(cfg, "REGION_HINT", "")] + region_kw[:2]
    parts = [item.get("title", "")] + tokens + regions
    query = " ".join(p for p in parts if p).strip()
    return query[:150]


# ---------------------------------------------------------------------------
# Openverse provider
# ---------------------------------------------------------------------------

_OPENVERSE_ENDPOINT = "https://api.openverse.engineering/v1/images/"


def _openverse(query: str, cfg=config) -> Optional[Dict]:
    params = {
        "q": query,
        "license": ",".join(_licenses(cfg)),
        "page_size": 1,
    }
    try:
        text = net.get_text(
            _OPENVERSE_ENDPOINT,
            params=params,
            timeout=cfg.HTTP_TIMEOUT_READ,
        )
        data = json.loads(text)
    except Exception:  # pragma: no cover - network issues
        return None

    for res in data.get("results", []):
        lic = (res.get("license") or "").lower()
        if lic not in _licenses(cfg):
            continue
        width = int(res.get("width") or 0)
        height = int(res.get("height") or 0)
        if width < cfg.IMAGE_MIN_EDGE or height < cfg.IMAGE_MIN_EDGE:
            continue
        if width * height < cfg.IMAGE_MIN_AREA:
            continue
        img_url = res.get("url") or res.get("thumbnail")
        if not img_url or not net.is_downloadable_image_url(img_url):
            continue
        payload = images.download_image(img_url)
        if not payload:
            continue
        raw, mime = payload
        author = res.get("creator")
        source = res.get("foreign_landing_url") or img_url
        credit = None
        if author or lic:
            credit = f"{author or ''} / {lic.upper()} (Openverse)".strip()
        return {
            "image_url": img_url,
            "bytes": raw,
            "mime": mime,
            "width": width,
            "height": height,
            "author": author,
            "license": lic,
            "source": source,
            "provider": "openverse",
            "credit": credit,
        }
    return None


# ---------------------------------------------------------------------------
# Wikimedia provider
# ---------------------------------------------------------------------------

_WIKIMEDIA_ENDPOINT = "https://commons.wikimedia.org/w/api.php"


def _wikimedia(query: str, cfg=config) -> Optional[Dict]:
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": query,
        "gsrlimit": 1,
        "prop": "imageinfo",
        "iiprop": "url|mime|size|extmetadata",
        "format": "json",
    }
    try:
        text = net.get_text(
            _WIKIMEDIA_ENDPOINT,
            params=params,
            timeout=cfg.HTTP_TIMEOUT_READ,
        )
        data = json.loads(text)
    except Exception:  # pragma: no cover
        return None
    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        lic = (
            info.get("extmetadata", {})
            .get("LicenseShortName", {})
            .get("value", "")
            .lower()
        )
        if lic not in _licenses(cfg):
            continue
        width = int(info.get("width") or 0)
        height = int(info.get("height") or 0)
        if width < cfg.IMAGE_MIN_EDGE or height < cfg.IMAGE_MIN_EDGE:
            continue
        if width * height < cfg.IMAGE_MIN_AREA:
            continue
        img_url = info.get("url")
        if not img_url or not net.is_downloadable_image_url(img_url):
            continue
        payload = images.download_image(img_url)
        if not payload:
            continue
        raw, mime = payload
        author = (
            info.get("extmetadata", {}).get("Artist", {}).get("value")
        )
        source = page.get("fullurl") or img_url
        credit = None
        if author or lic:
            credit = f"{author or ''} / {lic.upper()} (Wikimedia)".strip()
        return {
            "image_url": img_url,
            "bytes": raw,
            "mime": mime,
            "width": width,
            "height": height,
            "author": author,
            "license": lic,
            "source": source,
            "provider": "wikimedia",
            "credit": credit,
        }
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_context_image(item: Dict, cfg=config) -> Dict:
    """Return image dict from open sources or empty dict."""
    query = build_query(item, cfg)
    providers = [
        p.strip().lower()
        for p in getattr(cfg, "CONTEXT_IMAGE_PROVIDERS", "openverse,wikimedia").split(",")
        if p.strip()
    ]
    for prov in providers:
        res: Optional[Dict] = None
        if prov == "openverse":
            res = _openverse(query, cfg)
        elif prov == "wikimedia":
            res = _wikimedia(query, cfg)
        if res:
            return res
    return {}

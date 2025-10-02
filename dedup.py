# import-shim: allow running as a script (no package parent)
if __name__ == "__main__" or __package__ is None:
    import os
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
# end of shim

# newsbot/dedup.py
import hashlib
import os
import pathlib
import re
import sqlite3
import time
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

try:
    from . import config
    from . import db
    from . import utils
except ImportError:  # pragma: no cover - fallback for script execution
    import config  # type: ignore
    import db  # type: ignore
    import utils  # type: ignore

from logging_setup import get_logger
from webwork.dedup import (
    canonical_url,
    dedup_key as build_dedup_key,
    near_duplicate,
    title_norm,
)

logger = get_logger(__name__)

_WORD_RE = re.compile(r"[0-9a-zа-яё]+", re.I)

_TRACKING_PREFIXES = ("utm_", "yclid", "gclid", "fbclid", "spm", "_openstat")


def normalize_url(url: str | None) -> str:
    if not url:
        return ""
    raw = str(url).strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not any(key.lower().startswith(prefix) for prefix in _TRACKING_PREFIXES)
    ]
    cleaned = parsed._replace(
        netloc=host,
        query=urlencode(filtered_query, doseq=True),
        fragment="",
    )
    return urlunparse(cleaned)


def make_key(item: dict) -> str:
    url_fields = (
        "url",
        "URL",
        "link",
        "Link",
        "source_url",
        "SourceURL",
        "sourceURL",
        "sourceUrl",
    )
    normalized_url = ""
    for field in url_fields:
        value = item.get(field)
        if value:
            normalized_url = normalize_url(str(value))
            if normalized_url:
                break
    if normalized_url:
        return f"url:{normalized_url}"

    title = str(item.get("title") or "").strip().lower()
    domain_fields = ("source_domain", "domain", "source")
    domain = ""
    for field in domain_fields:
        value = item.get(field)
        if value:
            domain = str(value).strip().lower()
            if domain:
                break
    return f"title:{domain}:{title}"


def deduplicate(items: Sequence[Dict[str, object]], *, scope: str = "default") -> List[Dict[str, object]]:
    """Удалить дубли в памяти на основании URL/GUID/TG-ID."""

    seen: set[str] = set()
    result: List[Dict[str, object]] = []
    removed = 0
    for item in items:
        guid = str(item.get("guid") or "").strip()
        url = str(item.get("url") or "").strip()
        canon_url = canonical_url(url)
        alias = str(item.get("tg_alias") or "").strip().lower()
        tg_mid_raw = item.get("tg_msg_id")
        tg_mid = str(tg_mid_raw) if tg_mid_raw not in {None, ""} else ""
        key_candidates = [guid, canon_url or url]
        if alias and tg_mid:
            key_candidates.append(f"tg:{alias}:{tg_mid}")
        normalized_title = title_norm(item.get("title") or "")
        if normalized_title:
            key_candidates.append(normalized_title)
        hashed_key = build_dedup_key(url or None, item.get("title"))
        if hashed_key:
            key_candidates.append(f"hash:{hashed_key}")
        dedup_key = next((k for k in key_candidates if k), None)
        if not dedup_key:
            dedup_key = repr(item)
        if dedup_key in seen:
            removed += 1
            continue
        seen.add(dedup_key)
        result.append(dict(item))
    if removed and scope == "raw":
        logger.info("RAW: удалено %d дублей перед публикацией", removed)
    elif removed:
        logger.info("DEDUP: удалено %d дублей (scope=%s)", removed, scope)
    return result


def _tokenize(title: str) -> Tuple[set[str], set[str]]:
    text = utils.normalize_whitespace(title).lower()
    words = {w for w in _WORD_RE.findall(text) if len(w) > 2}
    letters = re.sub(r"[^0-9a-zа-яё]+", "", text)
    if len(letters) < 3:
        grams = {letters} if letters else set()
    else:
        grams = {letters[i : i + 3] for i in range(len(letters) - 2)}
    return words, grams


def _soft_overlap(words1: set[str], words2: set[str], *, min_ratio: float = 0.6) -> float:
    if not words1 or not words2:
        return 0.0
    remaining = list(words2)
    matches = 0
    for w1 in words1:
        best_idx = -1
        best_score = 0.0
        for idx, w2 in enumerate(remaining):
            ratio = SequenceMatcher(None, w1, w2).ratio()
            if ratio > best_score:
                best_score = ratio
                best_idx = idx
        if best_idx != -1 and best_score >= min_ratio:
            matches += 1
            remaining.pop(best_idx)
    if not matches:
        return 0.0
    return matches / min(len(words1), len(words2))


def _jaccard(a: Sequence[str] | set[str], b: Sequence[str] | set[str]) -> float:
    set_a = set(a)
    set_b = set(b)
    if not set_a or not set_b:
        return 0.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


class SeenStore:
    """Persistent storage for RAW deduplication guard."""

    def __init__(self, path: str = os.path.join("state", "seen.sqlite3")) -> None:
        self.path = path
        directory = os.path.dirname(path) or "."
        pathlib.Path(directory).mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS seen(" "kind TEXT, key TEXT, ts INTEGER, PRIMARY KEY(kind, key))"
        )

    def is_seen(self, kind: str, key: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM seen WHERE kind = ? AND key = ? LIMIT 1",
            (kind, key),
        )
        return cur.fetchone() is not None

    def mark(self, kind: str, key: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO seen(kind, key, ts) VALUES(?, ?, ?)",
            (kind, key, int(time.time())),
        )
        self.conn.commit()


def make_similarity_profile(title: str) -> Tuple[set[str], set[str]]:
    return _tokenize(title)


def profile_similarity(
    base_profile: Tuple[set[str], set[str]], other_profile: Tuple[set[str], set[str]]
) -> float:
    words1, grams1 = base_profile
    words2, grams2 = other_profile
    word_score = _jaccard(words1, words2)
    gram_score = _jaccard(grams1, grams2)
    soft_score = _soft_overlap(words1, words2)
    return max(word_score, gram_score, soft_score)


def title_similarity(lhs: str, rhs: str) -> float:
    """Compute similarity score between two titles using words and 3-grams."""

    if not lhs or not rhs:
        return 0.0

    return profile_similarity(_tokenize(lhs), _tokenize(rhs))


def similar_to_any(
    title: str,
    profiles: Sequence[Tuple[set[str], set[str]]],
    *,
    threshold: float,
) -> Tuple[bool, Tuple[set[str], set[str]]]:
    """Check similarity of ``title`` against cached profiles."""

    profile = make_similarity_profile(title)
    for other in profiles:
        if profile_similarity(profile, other) >= threshold:
            return True, profile
    return False, profile

# ---------- Title hash ----------

def calc_title_hash(title: str) -> str:
    """
    Normalize and hash a title to detect duplicates regardless of small formatting differences.
    """
    if not title:
        return ""
    text = title_norm(title)
    min_len = int(getattr(config, "DEDUP_TITLE_MIN_LEN", 10))
    if len(text) < min_len:
        return ""
    algo = getattr(config, "DEDUP_HASH_ALGO", "sha1").lower()
    h = hashlib.sha1 if algo == "sha1" else hashlib.md5
    return h(text.encode("utf-8")).hexdigest()

# ---------- Main check ----------

def is_duplicate(url: Optional[str], guid: Optional[str], title: Optional[str], db_conn) -> bool:
    """
    Returns True if the item was already seen (by URL, GUID or normalized title hash).
    """
    try:
        canonical = canonical_url(url)
        if url and db.exists_url(db_conn, url):
            return True
        if canonical and canonical != url and db.exists_url(db_conn, canonical):
            return True
        if guid and db.exists_guid(db_conn, guid):
            return True
        thash = calc_title_hash(title or "")
        if thash and db.exists_title_hash(db_conn, thash):
            return True
        if _has_similar_title(title or "", db_conn):
            return True
        return False
    except Exception as ex:
        logger.warning("Ошибка при проверке дублей: %s", ex)
        # Fail-open (treat as non-duplicate) to let pipeline continue
        return False

def remember(db_conn, item: dict) -> None:
    """
    Persist the item to the DB so future runs will treat it as seen.
    """
    # compute title hash once
    thash = calc_title_hash(item.get("title") or "")
    record = dict(item)
    record["title_hash"] = thash
    canonical = canonical_url(record.get("url"))
    if canonical:
        record["url"] = canonical
    try:
        db.upsert_item(db_conn, record)
    except Exception as ex:
        logger.warning("Не удалось сохранить элемент в БД: %s", ex)


def _has_similar_title(title: str, db_conn) -> bool:
    """Check if ``title`` is sufficiently similar to recent records."""

    if not getattr(config, "ENABLE_TITLE_CLUSTERING", False):
        return False

    normalized = utils.normalize_whitespace(title or "").lower()
    if not normalized:
        return False

    min_len = int(getattr(config, "DEDUP_TITLE_MIN_LEN", 10))
    if len(normalized) < min_len:
        return False

    lookback_days = int(getattr(config, "CLUSTER_LOOKBACK_DAYS", 0))
    if lookback_days <= 0:
        return False

    since_ts = int(time.time() - lookback_days * 86400)
    candidates_limit = max(1, int(getattr(config, "CLUSTER_MAX_CANDIDATES", 200)))
    threshold = float(getattr(config, "CLUSTER_SIM_THRESHOLD", 0.55))

    try:
        candidates = db.fetch_recent_titles(db_conn, since_ts, candidates_limit)
    except Exception as ex:  # pragma: no cover - DB errors are non-fatal
        logger.warning("Ошибка при загрузке заголовков для кластеризации: %s", ex)
        return False

    approx = near_duplicate(
        title,
        (cand_title for cand_title, _ in candidates),
        threshold=float(getattr(config, "NEAR_DUPLICATE_THRESHOLD", getattr(config, "CLUSTER_SIM_THRESHOLD", 0.9))),
    )
    if approx:
        logger.info("[DUP_SIMILAR] near duplicate %.2f with '%s'", approx[1], approx[0][:140])
        return True

    for cand_title, _ in candidates:
        cand_norm = utils.normalize_whitespace(cand_title or "").lower()
        if not cand_norm or cand_norm == normalized:
            continue
        if len(cand_norm) < min_len:
            continue
        score = title_similarity(normalized, cand_norm)
        if score >= threshold:
            logger.info(
                "[DUP_SIMILAR] совпадение %.2f с '%s'", score, (cand_title or "")[:140]
            )
            return True
    return False


def mark_published(
    *,
    url: Optional[str],
    guid: Optional[str],
    title: Optional[str],
    published_at: Optional[str],
    source: Optional[str],
    image_url: Optional[str] = None,
    db_conn,
) -> None:
    """Пометить материал как опубликованный, сохранив его в таблице ``items``.

    В БД записываются URL/GUID, нормализованный хеш заголовка и прочие
    основные поля, чтобы в дальнейшем корректно работать с антидублем.
    Ошибки при записи не считаются фатальными и логируются в warn.
    """

    record = {
        "url": canonical_url((url or "").strip()) or (url or "").strip(),
        "guid": (guid or "").strip(),
        "title": title or "",
        "title_hash": calc_title_hash(title or ""),
        "content": None,
        "source": source or "",
        "published_at": published_at or "",
        "image_url": image_url,
    }
    try:
        db.upsert_item(db_conn, record)
    except Exception as ex:  # pragma: no cover - ошибки не критичны
        logger.warning("Не удалось сохранить элемент в БД: %s", ex)

# newsbot/dedup.py
import hashlib
import logging
import re
import time
from difflib import SequenceMatcher
from typing import Optional

try:
    from . import db, utils, config
except ImportError:  # pragma: no cover
    import db, utils, config  # type: ignore

logger = logging.getLogger(__name__)

# ---------- Title hash ----------

def calc_title_hash(title: str) -> str:
    """
    Normalize and hash a title to detect duplicates regardless of small formatting differences.
    """
    if not title:
        return ""
    text = utils.normalize_whitespace(title).lower()
    # strip quotes, punctuation and extra spaces
    text = re.sub(r"[^0-9a-zа-яё ]+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text, flags=re.IGNORECASE).strip()
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
        if url and db.exists_url(db_conn, url):
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

    base_tokens = {t for t in normalized.split() if len(t) > 2}
    base_sorted_tokens = " ".join(sorted(normalized.split()))

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

    for cand_title, _ in candidates:
        cand_norm = utils.normalize_whitespace(cand_title or "").lower()
        if not cand_norm or cand_norm == normalized:
            continue
        if len(cand_norm) < min_len:
            continue
        cand_tokens = {t for t in cand_norm.split() if len(t) > 2}
        cand_sorted_tokens = " ".join(sorted(cand_norm.split()))
        token_union = base_tokens | cand_tokens
        token_score = 0.0
        if token_union:
            token_score = len(base_tokens & cand_tokens) / len(token_union)

        char_ratio = SequenceMatcher(None, normalized, cand_norm).ratio()
        sorted_ratio = SequenceMatcher(None, base_sorted_tokens, cand_sorted_tokens).ratio()

        coverage = 0.0
        if base_tokens and cand_tokens:
            shared = len(base_tokens & cand_tokens)
            coverage = max(
                shared / len(base_tokens),
                shared / len(cand_tokens),
            )

        score = max(char_ratio, token_score, sorted_ratio, coverage)
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
        "url": (url or "").strip(),
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

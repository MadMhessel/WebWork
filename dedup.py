# newsbot/dedup.py
import hashlib
import logging
import re
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

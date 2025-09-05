import logging
import re
from typing import Iterable, List, Union, Any

logger = logging.getLogger(__name__)

# -------------------- Вспомогательное --------------------

def _normalize_keywords(kw: Union[str, Iterable[Any], None]) -> List[str]:
    """
    Приводим keywords к списку строк (нижний регистр).
    Поддерживает:
      - строку с разделителями (',', ';', '|') -> сплит,
      - список/сет/кортеж -> по элементам,
      - None -> [].
    Пустые элементы отбрасываются.
    """
    if kw is None:
        return []
    if isinstance(kw, str):
        # Разрешим несколько типичных разделителей в строковых переменных окружения
        raw = re.split(r"[;,|]", kw)
        out = []
        for x in raw:
            s = (x or "").strip().lower()
            if s:
                out.append(s)
        return out
    out = []
    try:
        for x in kw:  # type: ignore
            s = (str(x) if x is not None else "").strip().lower()
            if s:
                out.append(s)
    except TypeError:
        # На случай неожиданных типов — вернём пусто
        return []
    return out


# -------------------- Нормализация и проверка ключевых слов --------------------

def normalize_text(s: str) -> str:
    """
    Нижний регистр + сжатие пробелов/переводов строк.
    """
    if not s:
        return ""
    s = s.replace("\u00a0", " ")  # NBSP -> space
    s = re.sub(r"\s+", " ", s, flags=re.U).strip().lower()
    return s


def contains_any(text: str, keywords: Iterable[str]) -> bool:
    """
    Простая проверка: хотя бы одно из keywords встречается в text (после normalize_text).
    Поддерживает как точные фразы, так и «стемы» (например, 'строител', 'реконструкц').
    """
    try:
        t = normalize_text(text)
        if not t:
            return False
        for kw in keywords:
            k = (kw or "").strip().lower()
            if not k:
                continue
            if k in t:
                return True
        return False
    except Exception as ex:
        logger.exception("contains_any: ошибка обработки текста: %s", ex)
        return False


# -------------------- Основная логика релевантности --------------------

def _slice_head(content: str, head_chars: int) -> str:
    if head_chars <= 0:
        return ""
    if len(content) <= head_chars:
        return content
    head = content[:head_chars]
    for sep in ["\n", ". ", " ", ""]:
        pos = head.rfind(sep)
        if pos > 0:
            return head[:pos]
    return head


def is_relevant(title: str, content: str, cfg) -> bool:
    """
    Базовая проверка релевантности:
      - регион: cfg.REGION_KEYWORDS
      - тематика: cfg.CONSTRUCTION_KEYWORDS
    Логика по умолчанию строгая «И» (cfg.STRICT_FILTER = true).
    Сканируем заголовок + «голову» текста на длину cfg.FILTER_HEAD_CHARS.
    """
    title = title or ""
    content = content or ""

    head_chars = int(getattr(cfg, "FILTER_HEAD_CHARS", 400))
    strict = bool(getattr(cfg, "STRICT_FILTER", True))

    region_kw = _normalize_keywords(getattr(cfg, "REGION_KEYWORDS", []))
    topic_kw  = _normalize_keywords(getattr(cfg, "CONSTRUCTION_KEYWORDS", []))

    text_for_check = f"{title}\n{_slice_head(content, head_chars)}"
    region_ok = contains_any(text_for_check, region_kw)
    topic_ok  = contains_any(text_for_check, topic_kw)

    ok = (region_ok and topic_ok) if strict else (region_ok or topic_ok)

    logger.debug(
        "is_relevant(strict=%s, head=%d) => region=%s topic=%s title='%s'",
        strict, head_chars, region_ok, topic_ok, title[:120]
    )
    return ok


def is_relevant_for_source(title: str, content: str, source_name: str, cfg) -> bool:
    """
    Обёртка над is_relevant с учётом белых списков.
    Если источник в cfg.WHITELIST_SOURCES и cfg.WHITELIST_RELAX=true —
    проверяем по ПОЛНОМУ тексту (но логика «И» остаётся строгой).
    Для остальных источников — как обычно (заголовок + голова).
    """
    title = title or ""
    content = content or ""
    src = (source_name or "").strip().lower()

    wl = set(_normalize_keywords(getattr(cfg, "WHITELIST_SOURCES", [])))
    relax = bool(getattr(cfg, "WHITELIST_RELAX", True))

    if src and src in wl and relax:
        strict = bool(getattr(cfg, "STRICT_FILTER", True))
        region_kw = _normalize_keywords(getattr(cfg, "REGION_KEYWORDS", []))
        topic_kw  = _normalize_keywords(getattr(cfg, "CONSTRUCTION_KEYWORDS", []))
        text_full = f"{title}\n{content}"
        region_ok = contains_any(text_full, region_kw)
        topic_ok  = contains_any(text_full, topic_kw)
        ok = (region_ok and topic_ok) if strict else (region_ok or topic_ok)
        logger.debug(
            "is_relevant_for_source[WHITELIST] src='%s' => region=%s topic=%s title='%s'",
            source_name, region_ok, topic_ok, title[:120]
        )
        return ok

    return is_relevant(title, content, cfg)

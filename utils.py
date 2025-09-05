# -*- coding: utf-8 -*-
import re
import hashlib
from typing import Any, Dict

_WS_RE = re.compile(r"\s+", re.U)

def normalize_whitespace(text: str) -> str:
    if not isinstance(text, str):
        return ""
    return _WS_RE.sub(" ", text).strip()

_PUNCT_RE = re.compile(r"[^\w\s]+", re.U)
def compute_title_hash(title: str) -> str:
    """
    Нормализованный хеш заголовка (для поиска почти дублей).
    - в нижний регистр
    - убираем пунктуацию
    - схлопываем пробелы
    """
    base = normalize_whitespace(title).lower()
    base = _PUNCT_RE.sub(" ", base)
    base = normalize_whitespace(base)
    return hashlib.sha1(base.encode("utf-8")).hexdigest()

def safe_get(d: Dict[str, Any], key: str, default: str = "") -> str:
    v = d.get(key, default)
    return v if isinstance(v, str) else default

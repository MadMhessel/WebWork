"""Utility rules and helpers for the autorewrite pipeline."""

from __future__ import annotations

import re
from typing import Dict, List, Pattern, Tuple

# --- Basic replacements ---------------------------------------------------

SYNONYMS: Dict[str, str] = {
    "построят": "возведут",
    "построить": "возвести",
    "строительство": "возведение",
    "застройщик": "девелопер",
    "введен в эксплуатацию": "запущен в работу",
    "ввели в эксплуатацию": "запустили",
    "ввести в эксплуатацию": "запустить в работу",
    "началось": "стартовало",
    "начался": "стартовал",
    "начнется": "стартует",
    "сообщил": "заявил",
    "сообщила": "заявила",
    "сообщили": "заявили",
    "ремонт": "ремонтные работы",
    "реконструкция": "обновление",
}

PATTERNS: List[Tuple[Pattern[str], str]] = [
    (re.compile(r"\bв рамках\b", re.IGNORECASE), "по проекту"),
    (re.compile(r"\bв целях\b", re.IGNORECASE), "чтобы"),
    (re.compile(r"\bв том числе\b", re.IGNORECASE), "включая"),
]

# География и типовые огрехи ------------------------------------------------

GEO_PATTERNS: List[Tuple[Pattern[str], str]] = [
    (re.compile(r"\bНижегородском регионе\b", re.IGNORECASE), "Нижегородской области"),
    (re.compile(r"\bв Нижегородском регионе\b", re.IGNORECASE), "в Нижегородской области"),
    (re.compile(r"\bНижегородский регион\b", re.IGNORECASE), "Нижегородская область"),
]

TYPO_PATTERNS: List[Tuple[Pattern[str], str]] = [
    (re.compile(r"\bгрузового\b(?!\s+транспорта)", re.IGNORECASE), "грузового транспорта"),
    (re.compile(r"\s+([,.!?])"), r"\1"),
    (re.compile(r"\.{2,}"), "."),
    (re.compile(r'"{2,}'), '"'),
]

LEAD_RE = re.compile(r"^(Коротко|Главное|Суть|Что произошло)\s*[:,]?\s*", re.IGNORECASE)

SOFT_LINKERS = ["Кроме того,", "Также", "При этом", "Дополнительно,"]

WORD_RE = re.compile(r"\b([А-ЯЁA-Z][а-яёa-z]+|[а-яёa-z]+|[A-Z]+|[0-9]+)\b", re.UNICODE)

# --- Text helpers ---------------------------------------------------------


def smart_replace_wordcase(src: str, repl: str) -> str:
    if not src:
        return repl
    if src.isupper():
        return repl.upper()
    if src[0].isupper():
        return repl.capitalize()
    return repl


def apply_synonyms(text: str) -> str:
    keys = sorted(SYNONYMS.keys(), key=len, reverse=True)
    out = text
    for k in keys:
        pattern = re.compile(re.escape(k), flags=re.IGNORECASE)
        out = pattern.sub(lambda m: smart_replace_wordcase(m.group(0), SYNONYMS[k]), out)
    return out


def apply_patterns(text: str) -> str:
    out = text
    for pat, repl in PATTERNS:
        out = pat.sub(repl, out)
    return out


def normalize_geo(text: str) -> str:
    out = text
    for pat, repl in GEO_PATTERNS:
        out = pat.sub(repl, out)
    return out


def fix_typos(text: str) -> str:
    out = text
    for pat, repl in TYPO_PATTERNS:
        out = pat.sub(repl, out)
    return out


def strip_leads(text: str) -> str:
    return LEAD_RE.sub("", text)


def compact_whitespace(s: str) -> str:
    return re.sub(r"[ \t]+", " ", s).strip()


# --- Sentence work --------------------------------------------------------

# Учитываем сокращения вида "т." и "г."
SENT_SPLIT_RE = re.compile(r"(?<!\b[тг]\.)(?<=[.!?])\s+", re.IGNORECASE)


def split_sentences(text: str) -> List[str]:
    text = strip_leads(compact_whitespace(text))
    if not text:
        return []
    parts = SENT_SPLIT_RE.split(text)
    out: List[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if p[-1] not in ".!?…":
            p += "."
        out.append(p)
    return out


# --- Sentence scoring -----------------------------------------------------

FACT_VERBS = [
    "введен", "введён", "запущен", "заработал", "заработала", "начал", "началась",
    "открыт", "открыла", "открыли", "построен", "создали",
]
KEY_TERMS = [
    "весогабарит", "штраф", "постановление", "центр обработки", "сервис",
    "нагрузк", "онлайн", "грузов", "проект",
]


def sentence_score(sent: str) -> float:
    low = sent.lower()
    score = 0.0
    for v in FACT_VERBS:
        if v in low:
            score += 2
    for term in KEY_TERMS:
        if term in low:
            score += 1.5
    score += 0.5 * len(re.findall(r"\d+", low))
    tokens = WORD_RE.findall(low)
    if len(tokens) > 25:
        score -= (len(tokens) - 25) * 0.1
    return score


# --- Public utility -------------------------------------------------------

__all__ = [
    "apply_synonyms",
    "apply_patterns",
    "normalize_geo",
    "fix_typos",
    "strip_leads",
    "split_sentences",
    "sentence_score",
    "SOFT_LINKERS",
    "compact_whitespace",
    "WORD_RE",
]

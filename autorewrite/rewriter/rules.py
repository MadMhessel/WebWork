import re
from typing import Dict, Pattern, List, Tuple

# Базовый список стоп-слов (минимальный)
STOP_WORDS_RU = {
    "и","в","во","не","что","он","на","я","с","со","как","а","то","все","она","так",
    "его","но","да","ты","к","у","же","вы","за","бы","по","ее","мне","есть","они",
    "тут","о","эту","ли","если","мы","когда","вы","были","ещё","из","для","это","при",
    "быть","от","до","после","г","год","лет","—","–"
}

# Доменные синонимы/замены под стройку и новости (расширяйте)
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
    "планируют": "намерены",
    "планируется": "намечено",
    "сообщил": "заявил",
    "сообщила": "заявила",
    "сообщили": "заявили",
    "Нижегородской области": "Нижегородском регионе",
    "Нижегородская область": "Нижегородский регион",
    "Нижний Новгород": "Нижнем Новгороде",
    "жилой комплекс": "ЖК",
    "квартиры": "апартаменты",
    "школа": "школьный корпус",
    "детский сад": "дошкольное учреждение",
    "инфраструктура": "объекты инфраструктуры",
    "капитальный ремонт": "капремонт",
    "ремонт": "ремонтные работы",
    "реконструкция": "обновление",
}

# Паттерны простых перефраз (регекс → замена)
PATTERNS: List[Tuple[Pattern[str], str]] = [
    # пассив → актив (очень грубые эвристики)
    (re.compile(r"\bбудет построен\b", flags=re.IGNORECASE), "планируют возвести"),
    (re.compile(r"\bбудут построены\b", flags=re.IGNORECASE), "намерены возвести"),
    (re.compile(r"\bбудет введен в эксплуатацию\b", flags=re.IGNORECASE), "планируют запустить"),
    (re.compile(r"\bбудут введены в эксплуатацию\b", flags=re.IGNORECASE), "планируют запустить в работу"),
    # канцелярит → нейтрально
    (re.compile(r"\bв рамках\b", flags=re.IGNORECASE), "по проекту"),
    (re.compile(r"\bв целях\b", flags=re.IGNORECASE), "чтобы"),
    (re.compile(r"\bв том числе\b", flags=re.IGNORECASE), "включая"),
]

# Простые клише/шаблоны для усиленного рерайта
LEADS = [
    "Коротко: {core}.",
    "Главное: {core}.",
    "Суть: {core}.",
    "Что произошло: {core}.",
]

TAILS = [
    "Подробности — ниже.",
    "Сроки и детали уточняются.",
    "Проект реализуют поэтапно.",
]

# Разделители предложений (очень аккуратно)
SENT_SPLIT_RE = re.compile(r"(?<=[\.!?])\s+")

def split_sentences(text: str) -> List[str]:
    text = text.strip()
    if not text:
        return []
    # Сохраняем точки в числах/сокращениях грубой эвристикой — минимально
    sents = SENT_SPLIT_RE.split(text)
    # чистим пустые
    return [s.strip() for s in sents if s.strip()]

WORD_RE = re.compile(r"\b([А-ЯЁA-Z][а-яёa-z]+|[а-яёa-z]+|[A-Z]+|[0-9]+)\b", re.UNICODE)

def smart_replace_wordcase(src: str, repl: str) -> str:
    # Сохранение регистра: Слово -> Слово / слово -> слово / СЛОВО -> СЛОВО
    if not src:
        return repl
    if src.isupper():
        return repl.upper()
    if src[0].isupper():
        return repl.capitalize()
    return repl

def apply_synonyms(text: str) -> str:
    # жадно по длинным ключам (чтобы "введен в эксплуатацию" шел раньше "эксплуатацию")
    keys = sorted(SYNONYMS.keys(), key=len, reverse=True)
    out = text
    for k in keys:
        # замена по словоформам будет ограниченной (русский сложен); используем точные вхождения/регистронезависимо
        pattern = re.compile(re.escape(k), flags=re.IGNORECASE)
        def _repl(m):
            src = m.group(0)
            return smart_replace_wordcase(src, SYNONYMS[k])
        out = pattern.sub(_repl, out)
    return out

def apply_patterns(text: str) -> str:
    out = text
    for pat, repl in PATTERNS:
        out = pat.sub(repl, out)
    return out

def compact_whitespace(s: str) -> str:
    return re.sub(r"[ \t]+", " ", s).strip()

def squeeze_newlines(s: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", s).strip()

def sentence_score(sent: str) -> int:
    # простая оценка "информативности": число значимых слов
    tokens = [w.lower() for w in WORD_RE.findall(sent)]
    return sum(1 for t in tokens if t not in STOP_WORDS_RU and len(t) > 2)

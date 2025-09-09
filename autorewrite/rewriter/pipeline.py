from typing import Dict, List, Tuple
import re
from .rules import (
    split_sentences, apply_synonyms, apply_patterns, compact_whitespace,
    squeeze_newlines, sentence_score, WORD_RE, LEADS, TAILS
)
from .similarity import normalize_for_shingles, shingles, jaccard, simhash, hamming_distance
from .markdown import escape_markdown_v2


def _limit_text(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    # стараемся резать по предложению
    sents = split_sentences(text)
    out = ""
    for s in sents:
        if len(out) + len(s) + 1 > max_len:
            break
        out += (s + " ")
    out = out.strip()
    if not out:
        return text[:max_len]
    return out


def _make_title(text: str, desired_len: int = 110) -> str:
    # базово: берем 1-е предложение, чистим вводные, режем до длины
    sents = split_sentences(text)
    base = sents[0] if sents else text
    # убираем служебные префиксы и агрегаторские поля
    base = re.sub(r"^Erid:[^,]+,\s*", "", base, flags=re.IGNORECASE)
    base = re.sub(r"^((Коротко|Главное|Суть|Что произошло)\s*[:,]?\s*)+", "", base, flags=re.IGNORECASE)
    # упрощаем заголовок
    base = re.sub(r"\b(сообщил[аи]?|рассказал[аи]?|заявил[аи]?|по словам|как сообщили)\b.*?$", "", base, flags=re.IGNORECASE)
    base = re.sub(r"^\s*(В|Во|На|По)\s+", "", base, flags=re.IGNORECASE)
    base = compact_whitespace(base)
    base = apply_patterns(apply_synonyms(base))
    if len(base) <= desired_len:
        return base.rstrip(".")
    # резка по словам
    words = base.split()
    out = []
    cur = 0
    for w in words:
        if cur + len(w) + (1 if out else 0) > desired_len:
            break
        out.append(w)
        cur += len(w) + (1 if out else 0)
    return compact_whitespace(" ".join(out)).rstrip("—–-,:;")


def _soft_rewrite(text: str) -> str:
    # мягкая фаза: синонимы + паттерны, легкая перестановка 2-3 лидирующих предложений
    sents = split_sentences(text)
    if not sents:
        return text
    sents = [apply_patterns(apply_synonyms(s)) for s in sents]
    # перестановка: если 2-3 предложения, меняем местами 1 и 2 (безопасно для новостей)
    if len(sents) == 2:
        sents = [sents[1], sents[0]]
    elif len(sents) >= 3:
        sents = [sents[1], sents[0]] + sents[2:]
    out = " ".join(sents)
    out = compact_whitespace(out)
    return out


def _compress(text: str, target_ratio: float = 0.85) -> str:
    # отбор наиболее информативных предложений по простому скору
    sents = split_sentences(text)
    if not sents:
        return text
    scores = [(sentence_score(s), i, s) for i, s in enumerate(sents)]
    scores.sort(reverse=True)  # по убыванию очков
    # берем ~N * ratio предложений, минимум 2
    n_take = max(2, int(len(sents) * target_ratio))
    best = sorted(scores[:n_take], key=lambda x: x[1])  # восстановить естественный порядок
    out = " ".join([x[2] for x in best])
    return compact_whitespace(out)


def _strong_rewrite(text: str) -> str:
    # усиливаем шаблоном: лид + факты, плюс хвост-клише
    sents = split_sentences(text)
    if not sents:
        return text
    # core: 1–2 самых информативных
    scores = [(sentence_score(s), i, s) for i, s in enumerate(sents)]
    scores.sort(reverse=True)
    core_sents = [x[2] for x in sorted(scores[:2], key=lambda y: y[1])]
    core = compact_whitespace(" ".join(core_sents))
    lead = LEADS[hash(text) % len(LEADS)].format(core=core)
    body_sents = [apply_patterns(apply_synonyms(s)) for s in sents[2:5]]  # чуть-чуть истории
    tail = TAILS[hash(core) % len(TAILS)]
    out = " ".join([lead] + body_sents + [tail])
    return compact_whitespace(out)


def _similarity_metrics(src: str, dst: str) -> Dict[str, float]:
    src_tokens = normalize_for_shingles(src)
    dst_tokens = normalize_for_shingles(dst)
    sh_a = shingles(src_tokens, 3)
    sh_b = shingles(dst_tokens, 3)
    jac = jaccard(sh_a, sh_b)
    sh1 = simhash(src_tokens)
    sh2 = simhash(dst_tokens)
    dist = hamming_distance(sh1, sh2)  # 0..64
    return {"jaccard": jac, "hamming": dist}


def _final_polish(text: str) -> str:
    text = compact_whitespace(text)
    text = squeeze_newlines(text)
    # точка в конце длинного поста
    if text and text[-1] not in ".!?…":
        text += "."
    return text


def rewrite_post(
    text: str,
    desired_len: int = 3500,
    min_hamming_distance: int = 16,
    max_jaccard: float = 0.85,
    desired_title_len: int = 110,
) -> Dict:
    """
    Главная функция рерайта.
    Возвращает dict: {title, text, similarity: {jaccard, hamming}, warnings: [...]}. 
    """
    original = compact_whitespace(text or "")
    warnings: List[str] = []
    if not original:
        return {
            "title": "",
            "text": "",
            "similarity": {"jaccard": 0.0, "hamming": 64},
            "warnings": ["Пустой входной текст"],
        }

    # Этап 1: мягкий
    v1 = _soft_rewrite(original)
    v1 = _limit_text(v1, desired_len)

    m1 = _similarity_metrics(original, v1)

    # Если уже ок по схожести — завершаем
    if m1["hamming"] >= min_hamming_distance and m1["jaccard"] <= max_jaccard:
        title = _make_title(v1, desired_len=desired_title_len)
        out = _final_polish(v1)
        return {
            "title": title,
            "text": out,
            "similarity": m1,
            "warnings": warnings,
        }

    # Этап 2: компрессия + легкий перефраз
    v2_base = _compress(original, target_ratio=0.8)
    v2 = _soft_rewrite(v2_base)
    v2 = _limit_text(v2, desired_len)
    m2 = _similarity_metrics(original, v2)

    if m2["hamming"] >= min_hamming_distance and m2["jaccard"] <= max_jaccard:
        title = _make_title(v2, desired_len=desired_title_len)
        out = _final_polish(v2)
        return {
            "title": title,
            "text": out,
            "similarity": m2,
            "warnings": ["Сработал фолбэк: компрессия+перефраз"],
        }

    # Этап 3: усиленный шаблонный рерайт
    v3 = _strong_rewrite(original)
    v3 = _limit_text(v3, desired_len)
    m3 = _similarity_metrics(original, v3)

    if not (m3["hamming"] >= min_hamming_distance and m3["jaccard"] <= max_jaccard):
        warnings.append("Результат остаётся слишком похожим на оригинал по метрикам — проверьте вручную.")
        warnings.append(f"Jaccard={m3['jaccard']:.3f} (порог {max_jaccard}), Hamming={int(m3['hamming'])} (порог {min_hamming_distance})")

    title = _make_title(v3, desired_len=desired_title_len)
    out = _final_polish(v3)

    return {
        "title": title,
        "text": out,
        "similarity": m3,
        "warnings": warnings or ["Сработал фолбэк: усиленный шаблон"],
    }

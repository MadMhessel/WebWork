"""Pipeline for rule-based news autorewrite."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List

from .rules import (
    apply_patterns,
    apply_synonyms,
    compact_whitespace,
    fix_typos,
    normalize_geo,
    sentence_score,
    split_sentences,
    strip_leads,
    SOFT_LINKERS,
)
from .similarity import (
    normalize_for_shingles,
    shingles,
    jaccard,
    simhash,
    hamming_distance,
)

# ---------------------------------------------------------------------------


def _get_cfg(cfg: Any, name: str, default):
    if cfg is not None and hasattr(cfg, name):
        try:
            val = getattr(cfg, name)
            if val is not None:
                return val
        except Exception:
            pass
    return type(default)(os.getenv(name, default))


def _limit_chars(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    cut = re.sub(r"\s+\S*$", "", cut)
    return cut + "…"


def _normalize_sentence(sent: str) -> str:
    s = normalize_geo(sent)
    s = apply_patterns(apply_synonyms(s))
    s = fix_typos(s)
    s = strip_leads(s)
    s = compact_whitespace(s)
    return s


def _add_linkers(sents: List[str]) -> List[str]:
    if len(sents) <= 1:
        return sents
    out = [sents[0]]
    idx = 0
    for s in sents[1:]:
        if any(s.lower().startswith(linker.lower()) for linker in SOFT_LINKERS):
            out.append(s)
            idx += 1
            continue
        linker = SOFT_LINKERS[idx % len(SOFT_LINKERS)]
        idx += 1
        out.append(f"{linker} {s}")
    return out


def _soft_rewrite(text: str) -> str:
    sents = [_normalize_sentence(s) for s in split_sentences(text)]
    if not sents:
        return text
    scores = [(sentence_score(s), i) for i, s in enumerate(sents)]
    scores.sort(key=lambda x: (-x[0], x[1]))
    key_idx = [i for _, i in scores[:4]]
    other_idx = [i for _, i in scores[4:6]]
    selected = [sents[i] for i in key_idx + [j for j in other_idx if j not in key_idx]]
    if len(selected) >= 2:
        selected[0], selected[1] = selected[1], selected[0]
    selected = _add_linkers(selected)
    return compact_whitespace(" ".join(selected))


def _strong_rewrite(text: str) -> str:
    sents = [_normalize_sentence(s) for s in split_sentences(text)]
    if not sents:
        return text
    scores = [(sentence_score(s), i) for i, s in enumerate(sents)]
    scores.sort(key=lambda x: (-x[0], x[1]))
    best_idx = [i for _, i in scores[:3]]
    chosen = [sents[i] for i in sorted(best_idx)]
    chosen = _add_linkers(chosen)
    return compact_whitespace(" ".join(chosen))


def _similarity_metrics(src: str, dst: str) -> Dict[str, float]:
    a = normalize_for_shingles(src)
    b = normalize_for_shingles(dst)
    sh_a = shingles(a, 3)
    sh_b = shingles(b, 3)
    jac = jaccard(sh_a, sh_b)
    h1 = simhash(a)
    h2 = simhash(b)
    dist = hamming_distance(h1, h2)
    return {"jaccard": jac, "hamming": dist}


def _final_polish(text: str) -> str:
    t = compact_whitespace(normalize_geo(fix_typos(strip_leads(text))))
    if t and t[-1] not in ".!?…":
        t += "."
    return t


def _make_title(text: str, limit: int) -> str:
    sents = split_sentences(text)
    base = sents[0] if sents else text
    base = strip_leads(base)
    base = re.sub(r"^Erid:[^,]+,\s*", "", base, flags=re.IGNORECASE)
    base = compact_whitespace(apply_patterns(apply_synonyms(base)))
    if len(base) <= limit:
        return base.rstrip("—–-,:;")
    words = base.split()
    out = []
    cur = 0
    for w in words:
        if cur + len(w) + (1 if out else 0) > limit:
            break
        out.append(w)
        cur += len(w) + (1 if out else 0)
    return compact_whitespace(" ".join(out)).rstrip("—–-,:;")


# ---------------------------------------------------------------------------


def rewrite_post(clean_text: str, cfg: Any | None = None) -> Dict[str, Any]:
    """Rewrite text returning title, body and similarity metrics."""

    original = compact_whitespace(clean_text or "")
    if not original:
        return {
            "title": "",
            "text": "",
            "similarity": {"jaccard": 0.0, "hamming": 64},
            "warnings": ["Пустой входной текст"],
        }

    max_jaccard = float(_get_cfg(cfg, "REWRITE_MAX_JACCARD", 0.72))
    min_hamming = int(_get_cfg(cfg, "REWRITE_MIN_HAMMING", 16))
    max_chars = int(_get_cfg(cfg, "REWRITE_MAX_CHARS", 600))
    title_len = int(_get_cfg(cfg, "REWRITE_TITLE_LEN", 120))

    # soft rewrite
    v1 = _soft_rewrite(original)
    v1 = _limit_chars(_final_polish(v1), max_chars)
    m1 = _similarity_metrics(original, v1)
    if m1["jaccard"] <= max_jaccard and m1["hamming"] >= min_hamming:
        title = _make_title(v1, title_len)
        return {"title": title, "text": v1, "similarity": m1, "warnings": []}

    # strong rewrite fallback
    v2 = _strong_rewrite(original)
    v2 = _limit_chars(_final_polish(v2), max_chars)
    m2 = _similarity_metrics(original, v2)
    warnings: List[str] = []
    if not (m2["jaccard"] <= max_jaccard and m2["hamming"] >= min_hamming):
        warnings.append("Результат остаётся слишком похожим на исходник.")
        warnings.append(f"Jaccard={m2['jaccard']:.3f}, Hamming={int(m2['hamming'])}")
    else:
        warnings.append("Сработал фолбэк: усиленный рерайт")

    title = _make_title(v2, title_len)
    return {"title": title, "text": v2, "similarity": m2, "warnings": warnings}

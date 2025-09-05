from __future__ import annotations
import logging, re
from typing import Iterable, List, Optional
log = logging.getLogger(__name__)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[\.!?])\s+")
_TAGS_RE = re.compile(r"<[^>]+>")
_SYNONYMS: List[tuple[re.Pattern, str]] = [
    (re.compile(r"\bсообщил(а|и)?\b"), "заявил\\1"),
    (re.compile(r"\bсообщает\b"), "заявляет"),
    (re.compile(r"\bсообщили\b"), "заявили"),
    (re.compile(r"\bначал(ось|ась|ись)\b"), "стартовал\\1"),
    (re.compile(r"\bпроходит\b"), "идёт"),
    (re.compile(r"\bбыло завершено\b"), "завершили"),
    (re.compile(r"\bв рамках\b"), "в составе"),
    (re.compile(r"\bреализаци(я|и)\b"), "выполнени\\1"),
    (re.compile(r"\bстроительств[оа]\b"), "возведение"),
    (re.compile(r"\bреконструкци(я|и)\b"), "обновлени\\1"),
]
_DEFAULT_REGION_HINTS = ("нижегородская область","нижний новгород","дзержинск","бор","кстово","сормово","автозаводский район","канавинский район")
_DEFAULT_TOPIC_HINTS = ("строи","жк","капремонт","реконструкц","ввод в эксплуатацию","подрядчик","генподряд","застройщик","инфраструктур","многоквартирн")

def _get_cfg_attr(cfg, name: str, default):
    try: return getattr(cfg, name)
    except Exception: return default

def _strip_tags(text: str) -> str: return _TAGS_RE.sub(" ", text or "")
def _normalize_ws(text: str) -> str:
    t = (text or "").replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\s+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

def _split_sentences(text: str) -> List[str]:
    text = _normalize_ws(text)
    if not text: return []
    parts = _SENTENCE_SPLIT_RE.split(text)
    return [p.strip() for p in parts if p.strip()]

def _join_sentences(sentences: Iterable[str]) -> str:
    out = " ".join(s.strip() for s in sentences if s and s.strip())
    return _normalize_ws(out)

def _apply_synonyms(text: str) -> str:
    t = f" {text} "
    for pat, repl in _SYNONYMS:
        try: t = pat.sub(repl, t)
        except Exception: pass
    return t.strip()

def _prioritize_sentences(sentences: List[str], region_hints: Iterable[str], topic_hints: Iterable[str]) -> List[str]:
    if not sentences: return sentences
    def score(s: str) -> int:
        sl = s.lower(); sc = 0
        for h in region_hints:
            if h in sl: sc += 2
        for h in topic_hints:
            if h in sl: sc += 1
        return sc
    indexed = list(enumerate(sentences))
    indexed.sort(key=lambda t: (-score(t[1]), t[0]))
    return [s for _, s in indexed]

def _limit_length(text: str, max_chars: int) -> str:
    if len(text) <= max_chars: return text
    sentences = _split_sentences(text); out = ""
    for s in sentences:
        if len(out) + len(s) + 1 <= max_chars: out = (out + " " + s).strip()
        else: break
    if not out:
        cut = text[:max_chars]
        cut = re.sub(r"\s+\S*$", "", cut).strip()
        return cut
    return out

def _rewrite_via_external_ai(original: str, cfg) -> Optional[str]:
    if not bool(_get_cfg_attr(cfg, "EXTERNAL_AI_ENABLED", False)): return None
    return None

def rewrite_text(original: str, cfg) -> str:
    try:
        if not original: return ""
        if not bool(_get_cfg_attr(cfg, "ENABLE_REWRITE", True)):
            return _normalize_ws(_strip_tags(original))
        ai_text = _rewrite_via_external_ai(original, cfg)
        if ai_text:
            result = _normalize_ws(_strip_tags(ai_text))
        else:
            clean = _normalize_ws(_strip_tags(original))
            sentences = _split_sentences(clean)
            region_hints = tuple(_get_cfg_attr(cfg, "REGION_KEYWORDS", _DEFAULT_REGION_HINTS))
            topic_hints = tuple(_get_cfg_attr(cfg, "CONSTRUCTION_KEYWORDS", _DEFAULT_TOPIC_HINTS))
            sentences = _prioritize_sentences(sentences, region_hints, topic_hints)
            sentences_syn = [_apply_synonyms(s) for s in sentences]
            result = _join_sentences(sentences_syn)
        tg_limit = int(_get_cfg_attr(cfg, "TELEGRAM_MESSAGE_LIMIT", 4096))
        rewrite_cap = int(_get_cfg_attr(cfg, "REWRITE_MAX_CHARS", min(900, tg_limit - 500)))
        result = _limit_length(result, max_chars=max(200, min(rewrite_cap, tg_limit - 200)))
        return result
    except Exception as ex:
        log.exception("Ошибка рерайта, используем бережное сокращение: %s", ex)
        safe = _normalize_ws(_strip_tags(original))
        tg_limit = int(_get_cfg_attr(cfg, "TELEGRAM_MESSAGE_LIMIT", 4096))
        return _limit_length(safe, max_chars=max(200, tg_limit - 200))

def maybe_rewrite_item(item: dict, cfg) -> dict:
    try:
        out = dict(item)
        summary = str(out.get("content", "") or "")
        out["content"] = rewrite_text(summary, cfg)
        return out
    except Exception:
        return item

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
import json
import re

import yaml

from utils import normalize_whitespace

CONFIG_PATH = Path(__file__).resolve().with_name("moderation.yaml")
PROFANITY_PATH = Path(__file__).resolve().with_name("profanity_ru.txt")

_RULES_CACHE: Dict[str, Any] | None = None
_PROFANITY_CACHE: List[str] | None = None
_PATTERN_CACHE: Dict[tuple[str, str], List[Dict[str, Any]]] = {}


@dataclass
class BlockResult:
    blocked: bool
    pattern: Optional[str] = None
    label: Optional[str] = None


@dataclass
class Flag:
    key: str
    pattern: str
    label: str
    requires_quality_note: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "pattern": self.pattern,
            "label": self.label,
            "requires_quality_note": bool(self.requires_quality_note),
        }


@dataclass
class ConfirmationVerdict:
    needs_confirmation: bool
    reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {"needs_confirmation": self.needs_confirmation, "reasons": list(self.reasons)}


def _load_rules() -> Dict[str, Any]:
    global _RULES_CACHE
    if _RULES_CACHE is None:
        with CONFIG_PATH.open("r", encoding="utf-8") as fh:
            _RULES_CACHE = yaml.safe_load(fh) or {}
    return _RULES_CACHE


def _load_profanity() -> List[str]:
    global _PROFANITY_CACHE
    if _PROFANITY_CACHE is None:
        patterns: List[str] = []
        if PROFANITY_PATH.exists():
            with PROFANITY_PATH.open("r", encoding="utf-8") as fh:
                for line in fh:
                    text = line.strip()
                    if not text or text.startswith("#"):
                        continue
                    patterns.append(text)
        _PROFANITY_CACHE = patterns
    return _PROFANITY_CACHE


def _expand_entry(entry: Any) -> List[Dict[str, Any]]:
    if isinstance(entry, dict):
        pattern = str(entry.get("pattern", "")).strip()
        label = entry.get("label")
        key = entry.get("id") or entry.get("key") or ""
    else:
        pattern = str(entry or "").strip()
        label = None
        key = ""
    if not pattern:
        return []
    if pattern == "@profanity_ru":
        return [
            {"pattern": p, "label": label or "profanity", "id": key or "profanity"}
            for p in _load_profanity()
        ]
    return [{"pattern": pattern, "label": label, "id": key}]


def _make_flag(entry: Dict[str, Any], *, requires_quality_note: bool = False) -> Flag:
    pattern = str(entry.get("pattern") or "")
    key = str(entry.get("id") or entry.get("key") or entry.get("label") or pattern or "")
    label = str(entry.get("label") or key)
    return Flag(key=key, pattern=pattern, label=label, requires_quality_note=requires_quality_note)


def _get_patterns(kind: str, rubric: Optional[str] = None) -> List[Dict[str, Any]]:
    key = (kind, rubric or "")
    cached = _PATTERN_CACHE.get(key)
    if cached is not None:
        return cached

    rules = _load_rules()
    patterns: List[Dict[str, Any]] = []
    for entry in rules.get(kind, []) or []:
        patterns.extend(_expand_entry(entry))

    overrides = (rules.get("rubric_overrides", {}) or {}).get(rubric or "", {})
    for entry in overrides.get(kind, []) or []:
        patterns.extend(_expand_entry(entry))

    _PATTERN_CACHE[key] = patterns
    return patterns


def _normalize_text(item: Dict[str, Any]) -> str:
    parts = [
        item.get("title", ""),
        item.get("summary", ""),
        item.get("content", ""),
        item.get("lead", ""),
    ]
    text = "\n".join(str(p or "") for p in parts)
    return normalize_whitespace(text.lower())


def run_blocklists(item: Dict[str, Any]) -> BlockResult:
    rubric = item.get("rubric")
    text = _normalize_text(item)
    if not text:
        return BlockResult(False)
    for entry in _get_patterns("block", rubric):
        pattern = entry.get("pattern")
        if not pattern:
            continue
        if re.search(pattern, text, flags=re.I | re.U):
            return BlockResult(True, pattern=pattern, label=entry.get("label"))
    return BlockResult(False)


def rubric_requires_quality_note(rubric: Optional[str]) -> bool:
    if not rubric:
        return False
    overrides = (_load_rules().get("rubric_overrides", {}) or {}).get(rubric, {})
    return bool(overrides.get("require_quality_note"))


def run_hold_flags(item: Dict[str, Any]) -> List[Flag]:
    rubric = item.get("rubric")
    text = _normalize_text(item)
    flags: List[Flag] = []
    if not text:
        return flags
    quality_note = rubric_requires_quality_note(rubric)
    for entry in _get_patterns("hold_for_review", rubric):
        pattern = entry.get("pattern")
        if not pattern:
            continue
        if re.search(pattern, text, flags=re.I | re.U):
            flags.append(_make_flag(entry, requires_quality_note=quality_note))
    return flags


def _extract_flag_keys(flags: Sequence[Any]) -> set[str]:
    keys: set[str] = set()
    for flag in flags:
        if isinstance(flag, Flag):
            if flag.key:
                keys.add(flag.key)
        elif isinstance(flag, dict):
            key = str(flag.get("key") or flag.get("id") or flag.get("label") or "").strip()
            if key:
                keys.add(key)
        else:
            try:
                keys.add(str(flag))
            except Exception:
                continue
    return keys


def _to_mapping(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _item_has_geo_and_topic(item: Dict[str, Any]) -> bool:
    reasons = _to_mapping(item.get("reasons"))
    region = bool(reasons.get("region") or reasons.get("region_ok"))
    topic = bool(reasons.get("topic") or reasons.get("topic_ok"))
    return region and topic


def _source_domains(sources: Sequence[Dict[str, Any]]) -> set[str]:
    domains: set[str] = set()
    for src in sources:
        domain = str(src.get("source_domain") or src.get("domain") or "").strip().lower()
        if domain:
            domains.add(domain)
    return domains


def _max_trust_level(sources: Sequence[Dict[str, Any]]) -> int:
    max_level = 0
    for src in sources:
        try:
            level = int(src.get("trust_level") or 0)
        except (TypeError, ValueError):
            level = 0
        if level > max_level:
            max_level = level
    return max_level


def _official_present(sources: Sequence[Dict[str, Any]]) -> bool:
    for src in sources:
        if src.get("is_official"):
            return True
        try:
            if int(src.get("trust_level") or 0) >= 3:
                return True
        except (TypeError, ValueError):
            continue
    return False


def run_deprioritize_flags(item: Dict[str, Any]) -> List[Flag]:
    rubric = item.get("rubric")
    text = _normalize_text(item)
    if not text:
        return []
    matches: List[Flag] = []
    for entry in _get_patterns("deprioritize", rubric):
        pattern = entry.get("pattern")
        if not pattern:
            continue
        if re.search(pattern, text, flags=re.I | re.U):
            matches.append(_make_flag(entry))

    rules = _load_rules()
    if matches and rules.get("allow_promo_if_objects_and_geo"):
        rubric_name = (item.get("rubric") or "").strip()
        if rubric_name == "objects" and _item_has_geo_and_topic(item):
            matches = [flag for flag in matches if flag.key != "promo"]
    return matches


def _evaluate_requirement(req: Dict[str, Any], sources: Sequence[Dict[str, Any]]) -> bool:
    if "sources_with_trust_level_gte" in req:
        target = int(req.get("sources_with_trust_level_gte") or 0)
        return _max_trust_level(sources) >= target
    if "independent_sources_count_gte" in req:
        target = int(req.get("independent_sources_count_gte") or 0)
        return len(_source_domains(sources)) >= target
    if "official_source_present" in req:
        expected = bool(req.get("official_source_present"))
        return _official_present(sources) == expected
    return False


def needs_confirmation(
    item: Dict[str, Any], flags: Sequence[Any] | Any, sources_ctx: Dict[str, Any]
) -> ConfirmationVerdict:
    rubric = item.get("rubric") or sources_ctx.get("rubric")
    parsed_flags = parse_flags(flags)
    if not parsed_flags:
        parsed_flags = parse_flags(sources_ctx.get("flags"))
    flag_keys = _extract_flag_keys(parsed_flags)
    sources: Sequence[Dict[str, Any]] = sources_ctx.get("sources") or []

    reasons: List[str] = []
    rules = _load_rules().get("confirmation_rules", []) or []
    for rule in rules:
        expr = str(rule.get("if") or "").strip()
        if not expr:
            continue
        matched = False
        if expr.startswith("hold_for_review.match(") and expr.endswith(")"):
            inside = expr[len("hold_for_review.match(") : -1]
            variants = [v.strip() for v in re.split(r"[|,]", inside) if v.strip()]
            if any(v in flag_keys for v in variants):
                matched = True
        elif expr.startswith("rubric =="):
            rhs = expr.split("==", 1)[1].strip()
            rhs = rhs.strip("'\"")
            if rhs and rhs == rubric:
                matched = True
        if not matched:
            continue

        requirement = rule.get("require") or {}
        ok = True
        if "any" in requirement:
            options = requirement.get("any") or []
            ok = any(
                _evaluate_requirement(opt, sources)
                for opt in options
                if isinstance(opt, dict)
            )
        elif "all" in requirement:
            options = requirement.get("all") or []
            ok = all(
                _evaluate_requirement(opt, sources)
                for opt in options
                if isinstance(opt, dict)
            )
        else:
            ok = _evaluate_requirement(requirement, sources)

        if not ok:
            reasons.append(expr)

    return ConfirmationVerdict(needs_confirmation=bool(reasons), reasons=reasons)


def check_confirmation_requirements(
    item: Dict[str, Any], sources_ctx: Dict[str, Any]
) -> ConfirmationVerdict:
    flags = sources_ctx.get("flags") or item.get("moderation_flags") or []
    return needs_confirmation(item, flags, sources_ctx)


def serialize_flags(flags: Iterable[Flag]) -> str:
    return json.dumps([flag.to_dict() for flag in flags], ensure_ascii=False)


def parse_flags(data: Any) -> List[Flag]:
    if not data:
        return []
    if isinstance(data, Flag):
        return [data]
    if isinstance(data, list):
        flags: List[Flag] = []
        for entry in data:
            flags.extend(parse_flags(entry))
        return [flag for flag in flags if isinstance(flag, Flag)]
    if isinstance(data, dict):
        if any(key in data for key in ("pattern", "key", "label", "id")) and not (
            "title" in data or "content" in data
        ):
            flag = _make_flag(data, requires_quality_note=bool(data.get("requires_quality_note")))
            return [flag]
        item = dict(data)
        return run_hold_flags(item) + run_deprioritize_flags(item)
    if isinstance(data, str):
        text = data.strip()
        if not text:
            return []
        if text.startswith("{") or text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if parsed is not None:
                return parse_flags(parsed)
        item = {"title": text, "content": text}
        return run_hold_flags(item) + run_deprioritize_flags(item)
    return []


def summarize_trust(sources: Sequence[Dict[str, Any]]) -> Dict[str, float]:
    if not sources:
        return {"min": 0.0, "avg": 0.0, "max": 0.0}
    levels: List[float] = []
    for src in sources:
        try:
            levels.append(float(src.get("trust_level") or 0.0))
        except (TypeError, ValueError):
            levels.append(0.0)
    minimum = min(levels) if levels else 0.0
    maximum = max(levels) if levels else 0.0
    average = sum(levels) / len(levels) if levels else 0.0
    return {"min": minimum, "avg": average, "max": maximum}


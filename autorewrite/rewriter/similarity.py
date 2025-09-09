import hashlib
import re
from typing import Iterable, Set, Tuple, List

_WORD_RE = re.compile(r"[А-Яа-яA-Za-z0-9\-]+")

def normalize_for_shingles(s: str) -> List[str]:
    tokens = [t.lower() for t in _WORD_RE.findall(s)]
    return tokens

def shingles(tokens: List[str], k: int = 3) -> Set[Tuple[str, ...]]:
    if k <= 0:
        return set()
    return {tuple(tokens[i:i+k]) for i in range(max(0, len(tokens)-k+1))}

def jaccard(a: Set[Tuple[str, ...]], b: Set[Tuple[str, ...]]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0

# Простой SimHash по словам
def _hash64(x: str) -> int:
    # Стабильный 64-битный хэш на базе sha1
    h = hashlib.sha1(x.encode("utf-8")).digest()
    # берем первые 8 байт
    return int.from_bytes(h[:8], "big", signed=False)

def simhash(tokens: Iterable[str]) -> int:
    bits = 64
    v = [0]*bits
    for t in tokens:
        h = _hash64(t)
        for i in range(bits):
            if (h >> i) & 1:
                v[i] += 1
            else:
                v[i] -= 1
    out = 0
    for i in range(bits):
        if v[i] >= 0:
            out |= (1 << i)
    return out

def hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()

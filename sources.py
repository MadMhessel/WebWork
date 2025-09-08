from typing import Iterable, Dict
try:
    from . import config
except ImportError:  # pragma: no cover
    import config  # type: ignore

def iter_sources() -> Iterable[Dict[str, str]]:
    for s in config.SOURCES:
        name = s.get("name", "").strip()
        url = s.get("url", "").strip()
        stype = (s.get("type") or "rss").strip().lower()
        if name and url:
            yield {"name": name, "url": url, "type": stype}

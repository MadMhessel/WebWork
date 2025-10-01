# import-shim: allow running as a script (no package parent)
if __name__ == "__main__" or __package__ is None:
    import os
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
# end of shim

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

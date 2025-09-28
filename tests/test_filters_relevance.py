import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))
from WebWork import filters


class Cfg:
    REGION_KEYWORDS = ["нижний", "область"]
    CONSTRUCTION_KEYWORDS = ["строител", "смр"]
    GLOBAL_KEYWORDS = ["глобал"]
    FILTER_HEAD_CHARS = 400
    STRICT_FILTER = True
    WHITELIST_SOURCES = {"trusted"}
    WHITELIST_RELAX = True


def test_relevant_strict_and_whitelist():
    ok, r, t, reason = filters.is_relevant("нижний строители", "", Cfg)
    assert ok and r and t and reason == ""

    ok, r, t, reason = filters.is_relevant("нижний", "", Cfg)
    assert not ok and r and not t and "тематики" in reason

    ok, r, t, reason = filters.is_relevant_for_source("нижний", "", "trusted", Cfg)
    assert ok and r and not t

    Cfg.STRICT_FILTER = False
    ok, r, t, reason = filters.is_relevant("", "смр", Cfg)
    assert ok and not r and t

    Cfg.STRICT_FILTER = True
    ok, r, t, reason = filters.is_relevant("глобал новости", "", Cfg)
    assert ok and not r and not t and reason == ""

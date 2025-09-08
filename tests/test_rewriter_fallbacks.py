import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from rewriter import run_rewrite_with_fallbacks, RewriterChainConfig
from rewriter.base import NewsItem


def test_llm_disabled_fallback_to_rules():
    item = NewsItem(id="1", source="s", url="u", title="t", text="купить квартиру")
    cfg = RewriterChainConfig(order=["llm", "rules", "noop"])
    res = run_rewrite_with_fallbacks(item, cfg)
    assert res.provider == "rules"
    assert "купить" not in res.text

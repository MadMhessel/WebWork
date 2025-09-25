import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from rewriter import run_rewrite_with_fallbacks, RewriterChainConfig
from rewriter.base import NewsItem


def test_rewriter_chain_defaults_to_noop():
    item = NewsItem(id="1", source="s", url="u", title="t", text="купить квартиру")
    cfg = RewriterChainConfig(order=["noop", "nonexistent"])
    res = run_rewrite_with_fallbacks(item, cfg)
    assert res.provider == "noop"
    assert res.text == "купить квартиру"

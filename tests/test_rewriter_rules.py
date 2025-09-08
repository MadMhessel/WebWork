import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from rewriter.rules import RuleBasedRewriter, RuleConfig
from rewriter.base import NewsItem


def test_remove_cta_and_normalize_spaces():
    item = NewsItem(id="1", source="s", url="u", title="Купить дом", text="Скидка 5%   купить!")
    rw = RuleBasedRewriter(RuleConfig())
    res = rw.rewrite(item)
    assert "купить" not in res.title.lower()
    assert "скидка" not in res.text.lower()
    assert "  " not in res.text

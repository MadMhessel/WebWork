from types import SimpleNamespace

from rewriter.base import RewriterResult
from rewriter_module import Rewriter
from rewriter.rules import RuleBasedRewriter


def test_uses_rule_engine(monkeypatch):
    called: dict[str, object] = {}

    def fake_rewrite(self, item, *, max_len=None):  # type: ignore[no-redef]
        called["title"] = item.title
        called["text"] = item.text
        called["max_len"] = max_len
        return RewriterResult(ok=True, title=item.title, text="переписано", provider="test")

    monkeypatch.setattr(RuleBasedRewriter, "rewrite", fake_rewrite, raising=False)
    cfg = SimpleNamespace()
    r = Rewriter(cfg)
    out = r.rewrite("Заголовок", "<p>Текст</p>", 200, "Нижегородская область")

    assert out == "переписано"
    assert called["title"] == "Заголовок"
    assert called["text"] == "Текст"
    assert called["max_len"] == 200


def test_returns_clean_text_by_default():
    cfg = SimpleNamespace()
    r = Rewriter(cfg)
    out = r.rewrite("t", "<p>купить квартиру у нас</p>", 100, "")
    assert "купить" not in out
    assert "квартиру" in out


def test_length_limited(monkeypatch):
    def fake_rewrite(self, item, *, max_len=None):  # type: ignore[no-redef]
        return RewriterResult(
            ok=True,
            title=item.title,
            text="a" * 5000,
            provider="test",
        )

    monkeypatch.setattr(RuleBasedRewriter, "rewrite", fake_rewrite, raising=False)
    cfg = SimpleNamespace()
    r = Rewriter(cfg)
    out = r.rewrite("t", "<p>x</p>", 100, "")
    assert len(out) == 100

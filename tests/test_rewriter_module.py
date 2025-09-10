from rewriter_module import Rewriter
import yandex_llm


def test_uses_yandex_llm(monkeypatch):
    called = {}

    def fake(prompt, target_chars, topic_hint, region_hint):
        called['args'] = (prompt, target_chars, topic_hint, region_hint)
        return "переписанный текст"

    monkeypatch.setattr(yandex_llm, "rewrite", fake)
    r = Rewriter()
    out = r.rewrite("Заголовок", "<p>Текст</p>", 200, "Нижегородская область")
    assert out == "переписанный текст"
    assert called['args'][1] == 200


def test_returns_original_on_error(monkeypatch):
    def fake(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(yandex_llm, "rewrite", fake)
    r = Rewriter()
    out = r.rewrite("t", "<p>оригинал</p>", 100, "")
    assert "оригинал" in out


def test_length_limited(monkeypatch):
    def fake(prompt, target_chars, topic_hint, region_hint):
        return "a" * 5000

    monkeypatch.setattr(yandex_llm, "rewrite", fake)
    r = Rewriter()
    out = r.rewrite("t", "<p>x</p>", 100, "")
    assert len(out) == 100

from types import SimpleNamespace

from rewriter_module import Rewriter
import yandex_llm


def test_uses_yandex_llm(monkeypatch):
    called = {}

    def fake(prompt, target_chars, topic_hint, region_hint):
        called['args'] = (prompt, target_chars, topic_hint, region_hint)
        return "переписанный текст"

    monkeypatch.setattr(yandex_llm, "rewrite", fake)
    cfg = SimpleNamespace(
        YANDEX_REWRITE_ENABLED=True,
        YANDEX_API_MODE="openai",
        YANDEX_API_KEY="k",
        YANDEX_FOLDER_ID="f",
    )
    r = Rewriter(cfg)
    out = r.rewrite("Заголовок", "<p>Текст</p>", 200, "Нижегородская область")
    assert out == "переписанный текст"
    assert called['args'][1] == 200


def test_returns_original_on_error(monkeypatch):
    def fake(*a, **k):
        raise yandex_llm.ServerError("boom")

    monkeypatch.setattr(yandex_llm, "rewrite", fake)
    cfg = SimpleNamespace(
        YANDEX_REWRITE_ENABLED=True,
        YANDEX_API_MODE="openai",
        YANDEX_API_KEY="k",
        YANDEX_FOLDER_ID="f",
    )
    r = Rewriter(cfg)
    out = r.rewrite("t", "<p>купить квартиру</p>", 100, "")
    assert "купить" not in out


def test_length_limited(monkeypatch):
    def fake(prompt, target_chars, topic_hint, region_hint):
        return "a" * 5000

    monkeypatch.setattr(yandex_llm, "rewrite", fake)
    cfg = SimpleNamespace(
        YANDEX_REWRITE_ENABLED=True,
        YANDEX_API_MODE="openai",
        YANDEX_API_KEY="k",
        YANDEX_FOLDER_ID="f",
    )
    r = Rewriter(cfg)
    out = r.rewrite("t", "<p>x</p>", 100, "")
    assert len(out) == 100

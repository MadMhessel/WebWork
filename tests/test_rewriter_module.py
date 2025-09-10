from rewriter_module import Rewriter


def test_rule_based_preserves_numbers_and_bullets():
    html = "<p>В регионе построили 10 домов. Ещё 5 запланировано.</p>"
    r = Rewriter()
    out = r.rewrite("Заголовок", html, 200, "Нижегородская область")
    assert "10" in out and "5" in out
    assert out.count("•") >= 1


def test_fallback_from_llm():
    html = "<p>Тестовое сообщение.</p>"
    r = Rewriter(use_llm=True)
    out = r.rewrite("Title", html, 50, "")
    assert "Тестовое сообщение" in out


def test_length_limited():
    body = "<p>" + "a" * 5000 + "</p>"
    r = Rewriter()
    out = r.rewrite("t", body, 100, "")
    assert len(out) <= 100

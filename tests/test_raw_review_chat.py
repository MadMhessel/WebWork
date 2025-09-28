import importlib


def test_raw_review_chat_prefers_specific_env(monkeypatch):
    module = importlib.import_module("webwork.config")

    # Ensure cached configuration does not leak between tests
    module.load_all.cache_clear()  # type: ignore[attr-defined]

    monkeypatch.setenv("REVIEW_CHAT_ID", "@main_mod")
    monkeypatch.setenv("RAW_REVIEW_CHAT_ID", "@raw_mod")

    cfg = module.load_all()  # type: ignore[call-arg]
    assert cfg.raw.review_chat_id == "@raw_mod"

    module.load_all.cache_clear()  # type: ignore[attr-defined]

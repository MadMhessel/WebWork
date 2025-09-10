import types
from unittest.mock import Mock

import pytest

import yandex_llm
from yandex_llm import ServerError


class DummyResp:
    def __init__(self, status_code=200, data=None, headers=None, text=""):
        self.status_code = status_code
        self._data = data or {}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._data


def _mk_cfg(**over):
    cfg = types.SimpleNamespace(
        ENABLE_LLM_REWRITE=True,
        YANDEX_API_MODE="openai",
        YANDEX_API_KEY="k",
        YANDEX_IAM_TOKEN="t",
        YANDEX_FOLDER_ID="f",
        YANDEX_MODEL="m",
        YANDEX_TEMPERATURE=0.2,
        YANDEX_MAX_TOKENS=100,
        YANDEX_TIMEOUT_CONNECT=5,
        YANDEX_TIMEOUT_READ=30,
        YANDEX_RETRIES=1,
        YANDEX_TOP_P=1,
        YANDEX_REQUESTS_PER_MINUTE=60,
    )
    for k, v in over.items():
        setattr(cfg, k, v)
    return cfg


def test_openai_parsing(monkeypatch):
    cfg = _mk_cfg()
    monkeypatch.setattr(yandex_llm, "config", cfg)
    resp = DummyResp(
        data={"choices": [{"message": {"content": "ответ" + "!" * 200}}]},
    )
    post = Mock(return_value=resp)

    class Sess:
        def post(self, *a, **kw):
            return post(*a, **kw)

    monkeypatch.setattr(yandex_llm.http_client, "get_session", lambda: Sess())
    out = yandex_llm.rewrite("текст", target_chars=50, topic_hint=None, region_hint=None)
    assert "ответ" in out
    assert len(out) <= 50
    post.assert_called_once()


def test_rest_parsing(monkeypatch):
    cfg = _mk_cfg(YANDEX_API_MODE="rest")
    monkeypatch.setattr(yandex_llm, "config", cfg)
    resp = DummyResp(
        data={"result": {"alternatives": [{"message": {"text": "ok"}}]}},
    )
    post = Mock(return_value=resp)

    class Sess:
        def post(self, *a, **kw):
            return post(*a, **kw)

    monkeypatch.setattr(yandex_llm.http_client, "get_session", lambda: Sess())
    assert yandex_llm.rewrite("текст", target_chars=10, topic_hint=None, region_hint=None) == "ok"


def test_retry_on_429(monkeypatch):
    cfg = _mk_cfg()
    monkeypatch.setattr(yandex_llm, "config", cfg)
    resp1 = DummyResp(status_code=429, headers={"Retry-After": "0"}, text="rl")
    resp2 = DummyResp(data={"choices": [{"message": {"content": "done"}}]})
    post = Mock(side_effect=[resp1, resp2])

    class Sess:
        def post(self, *a, **kw):
            return post(*a, **kw)

    monkeypatch.setattr(yandex_llm.http_client, "get_session", lambda: Sess())
    out = yandex_llm.rewrite("текст", target_chars=100, topic_hint=None, region_hint=None)
    assert out == "done"
    assert post.call_count == 2


def test_fallback_error(monkeypatch):
    cfg = _mk_cfg()
    monkeypatch.setattr(yandex_llm, "config", cfg)
    post = Mock(return_value=DummyResp(status_code=500, text="boom"))

    class Sess:
        def post(self, *a, **kw):
            return post(*a, **kw)

    monkeypatch.setattr(yandex_llm.http_client, "get_session", lambda: Sess())
    with pytest.raises(ServerError):
        yandex_llm.rewrite("текст", target_chars=10, topic_hint=None, region_hint=None)
    assert post.call_count == 2

import json

from WebWork import publisher


class _DummyResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


def test_api_post_retries_after_floodwait(monkeypatch):
    calls = []
    sleep_calls = []

    def fake_post(url, data=None, files=None, timeout=None):  # noqa: D401 - test stub
        calls.append((url, data))
        if len(calls) == 1:
            return _DummyResponse(429, {"ok": False, "parameters": {"retry_after": 1}})
        return _DummyResponse(200, {"ok": True, "result": {"message_id": "123"}})

    def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(publisher, "_client_base_url", "https://api.telegram.org/botTEST")
    monkeypatch.setattr(publisher, "_ensure_client", lambda: True)
    monkeypatch.setattr(publisher.requests, "post", fake_post)
    monkeypatch.setattr(publisher.time, "sleep", fake_sleep)

    result = publisher._api_post("sendMessage", {"chat_id": "1", "text": "hi"})
    assert result == {"ok": True, "result": {"message_id": "123"}}
    assert len(calls) == 2
    assert sleep_calls == [1]

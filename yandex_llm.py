"""Client for YandexGPT used for news rewriting.

This module exposes a single :func:`rewrite` function which sends a prompt to
YandexGPT and returns processed plain text.  Two API modes are supported:

``OPENAI_COMPAT``
    ``POST https://llm.api.cloud.yandex.net/v1/chat/completions``
    Authorisation via ``Authorization: Api-Key <YANDEX_API_KEY>``

``REST_COMPLETION``
    ``POST https://llm.api.cloud.yandex.net/foundationModels/v1/completion``
    Authorisation via ``Authorization: Bearer <YANDEX_IAM_TOKEN>``

The function is intentionally small yet feature complete: it handles timeouts,
rate limiting and result post-processing as required by the specification.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional
import re

import requests

try:  # pragma: no cover - import fallback
    import config  # type: ignore
    import http_client  # type: ignore
    from formatting import truncate_by_chars
except Exception:  # pragma: no cover
    import config  # type: ignore
    import http_client  # type: ignore
    from formatting import truncate_by_chars  # type: ignore

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions


class YandexLLMError(RuntimeError):
    """Base class for YandexGPT related errors."""

    label = "ERROR"


class InvalidAuthError(YandexLLMError):
    label = "INVALID_AUTH"


class PermissionError(YandexLLMError):
    label = "PERMISSION"


class RateLimitError(YandexLLMError):
    label = "RATE_LIMIT"


class ServerError(YandexLLMError):
    label = "SERVER_ERROR"


class TimeoutError(YandexLLMError):
    label = "TIMEOUT"


# ---------------------------------------------------------------------------
# Throttling: local requests per minute limit

_request_times: deque[float] = deque()


def _check_rpm_limit() -> None:
    limit = int(getattr(config, "YANDEX_REQUESTS_PER_MINUTE", 60))
    now = time.monotonic()
    while _request_times and now - _request_times[0] > 60:
        _request_times.popleft()
    if len(_request_times) >= limit:
        raise RateLimitError("local rate limit exceeded")
    _request_times.append(now)


# ---------------------------------------------------------------------------
# Helpers


def _guard_prompt(topic_hint: Optional[str], region_hint: Optional[str]) -> str:
    base = (
        "Перепиши новость кратко (600–800 символов по умолчанию), фактологично, без выдумок и оценочных суждений. "
        "Сохраняй числа, даты, имена собственные; приводимые цитаты — короткие, без канцелярита; без эмодзи/хештегов. "
        "Фокус: Нижегородская область; тематика: строительство/ремонт/инфраструктура/ЖК/мосты/дороги — "
        "если текст не про это, осторожно сокращай до информ-сводки без домыслов."
    )
    extra = []
    if topic_hint:
        extra.append(f"Тематика: {topic_hint}.")
    if region_hint:
        extra.append(f"Регион: {region_hint}.")
    if extra:
        base = base + " " + " ".join(extra)
    return base


def _clean_text(text: str, target_chars: int) -> str:
    """Post-process model output: remove unwanted fragments and limit length."""

    # remove emojis
    text = re.sub(r"[\U00010000-\U0010ffff]", "", text)
    # remove hashtags
    text = re.sub(r"#[^\s]+", "", text)
    # remove advertisement phrases
    text = re.sub(r"(?i)подпис\w+[^\n]*", "", text)
    text = re.sub(r"(?i)читай[^\n]*нас", "", text)
    # normalise whitespace
    text = re.sub(r" +", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    text = truncate_by_chars(text, target_chars)
    return text


# ---------------------------------------------------------------------------
# Main API


@dataclass
class _RequestParams:
    url: str
    headers: dict
    payload: dict


def _build_request(text: str, *, target_chars: int, topic_hint: Optional[str], region_hint: Optional[str]) -> _RequestParams:
    mode = getattr(config, "YANDEX_API_MODE", "openai").lower()
    temperature = float(getattr(config, "YANDEX_TEMPERATURE", 0.2))
    max_tokens = int(getattr(config, "YANDEX_MAX_TOKENS", 800))
    top_p = float(getattr(config, "YANDEX_TOP_P", 1.0))
    model = getattr(config, "YANDEX_MODEL", "yandexgpt-lite")
    folder = getattr(config, "YANDEX_FOLDER_ID", "")
    prompt = _guard_prompt(topic_hint, region_hint)

    if mode == "openai":
        api_key = getattr(config, "YANDEX_API_KEY", "")
        if not api_key or not folder:
            raise InvalidAuthError("missing API key or folder id")
        url = "https://llm.api.cloud.yandex.net/v1/chat/completions"
        headers = {"Authorization": f"Api-Key {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": f"gpt://{folder}/{model}/latest",
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": text},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
        }
        return _RequestParams(url, headers, payload)
    elif mode == "rest":
        iam_token = getattr(config, "YANDEX_IAM_TOKEN", "")
        if not iam_token or not folder:
            raise InvalidAuthError("missing IAM token or folder id")
        url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
        headers = {"Authorization": f"Bearer {iam_token}", "Content-Type": "application/json"}
        payload = {
            "modelUri": f"gpt://{folder}/{model}",
            "completionOptions": {
                "temperature": temperature,
                "maxTokens": max_tokens,
                "topP": top_p,
            },
            "messages": [
                {"role": "system", "text": prompt},
                {"role": "user", "text": text},
            ],
        }
        return _RequestParams(url, headers, payload)
    else:  # pragma: no cover - defensive
        raise ValueError(f"unknown YANDEX_API_MODE: {mode}")


def _parse_response(data: dict) -> str:
    if "choices" in data:
        return data["choices"][0]["message"]["content"].strip()
    if "result" in data:
        return data["result"]["alternatives"][0]["message"]["text"].strip()
    raise ServerError("invalid response format")


def rewrite(
    text: str,
    *,
    target_chars: int,
    topic_hint: Optional[str] = None,
    region_hint: Optional[str] = None,
) -> str:
    """Rewrite ``text`` using YandexGPT and return cleaned plain text."""

    if not getattr(config, "YANDEX_REWRITE_ENABLED", False):
        raise PermissionError("Yandex rewrite disabled")

    _check_rpm_limit()

    params = _build_request(
        text, target_chars=target_chars, topic_hint=topic_hint, region_hint=region_hint
    )

    sess = http_client.get_session()
    timeout = (
        float(getattr(config, "YANDEX_TIMEOUT_CONNECT", 5)),
        float(getattr(config, "YANDEX_TIMEOUT_READ", 30)),
    )
    retries = int(getattr(config, "YANDEX_RETRIES", 2))

    for attempt in range(retries + 1):
        start = time.monotonic()
        try:
            resp = sess.post(
                params.url,
                headers=params.headers,
                json=params.payload,
                timeout=timeout,
                verify=True,
            )
        except requests.Timeout as exc:
            log.error("yandex timeout: %s", exc)
            raise TimeoutError(str(exc)) from exc
        except requests.RequestException as exc:  # pragma: no cover - network
            log.error("yandex network error: %s", exc)
            raise ServerError(str(exc)) from exc

        duration = time.monotonic() - start
        log.info(
            "yandex request completed in %.2fs (status %s)", duration, resp.status_code
        )
        if resp.status_code == 200:
            data = resp.json()
            text_out = _parse_response(data)
            cleaned = _clean_text(text_out, target_chars)
            if len(text_out) > len(cleaned):
                log.warning("yandex output truncated to %d chars", target_chars)
            log.info("yandex reply length %d", len(cleaned))
            return cleaned

        if resp.status_code in {401, 400}:
            raise InvalidAuthError(resp.text)
        if resp.status_code == 403:
            raise PermissionError(resp.text)
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt < retries:
                retry_after = resp.headers.get("Retry-After")
                delay = 0.0
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        delay = 0.0
                else:
                    delay = 2 ** attempt
                log.warning(
                    "yandex request failed (%s), retrying in %.1fs", resp.status_code, delay
                )
                time.sleep(delay)
                continue
            if resp.status_code == 429:
                raise RateLimitError(resp.text)
            raise ServerError(resp.text)
        raise ServerError(resp.text)

    raise ServerError("unreachable state")


__all__ = [
    "rewrite",
    "YandexLLMError",
    "InvalidAuthError",
    "PermissionError",
    "RateLimitError",
    "ServerError",
    "TimeoutError",
]

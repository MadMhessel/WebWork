from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional

import requests

try:
    from .base import NewsItem, Rewriter, RewriterResult
except Exception:  # pragma: no cover
    from rewriter.base import NewsItem, Rewriter, RewriterResult  # type: ignore
try:
    from .. import config  # package import
except Exception:  # pragma: no cover
    import config  # type: ignore

OPENAI_COMPAT_URL = "https://llm.api.cloud.yandex.net/v1/chat/completions"

SYSTEM_PROMPT = (
    "Ты — редактор новостей для Telegram-канала о строительстве в Нижегородской области. "
    "Перепиши текст кратко и нейтрально, без оценок и домыслов. Сохраняй факты, цифры, даты, имена, топонимы. "
    "Фокус: строительство/инфраструктура/дороги/мосты/ЖК/реконструкция. "
    "Итог: 600–800 символов, 2–4 коротких абзаца, без эмодзи и хештегов."
)


@dataclass
class LLMConfig:
    provider: str = "yandex"
    model: str = ""
    temperature: float = 0.2
    max_tokens: int = 800


class LLMRewriter(Rewriter):
    """Рабочий адаптер к Яндекс LLM (OpenAI-совместимый endpoint)."""

    def __init__(self, cfg: Optional[LLMConfig] = None) -> None:
        self.cfg = cfg or LLMConfig(
            model=getattr(config, "YANDEX_MODEL", "yandexgpt-lite"),
            temperature=float(getattr(config, "YANDEX_TEMPERATURE", 0.2)),
            max_tokens=int(getattr(config, "YANDEX_MAX_TOKENS", 800)),
        )
        self._api_key = getattr(config, "YANDEX_API_KEY", "")
        self._folder_id = getattr(config, "YANDEX_FOLDER_ID", "")

    def _request(self, payload: dict) -> dict:
        headers = {
            "Authorization": f"Api-Key {self._api_key}",
            "Content-Type": "application/json",
        }
        # Небольшой backoff на 429/5xx
        retries = int(getattr(config, "YANDEX_RETRIES", 2))
        connect_to = float(getattr(config, "YANDEX_TIMEOUT_CONNECT", 5))
        read_to = float(getattr(config, "YANDEX_TIMEOUT_READ", 30))
        for attempt in range(retries + 1):
            r = requests.post(
                OPENAI_COMPAT_URL,
                headers=headers,
                data=json.dumps(payload, ensure_ascii=False),
                timeout=(connect_to, read_to),
            )
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                ra = r.headers.get("Retry-After")
                time.sleep(float(ra) if ra and ra.isdigit() else 0.8 * (2 ** attempt))
                continue
            r.raise_for_status()
            return r.json()
        # если дошли сюда — вернём последний ответ (raise_for_status уже был)
        return r.json()

    def rewrite(self, item: NewsItem, *, max_len: int | None = None) -> RewriterResult:
        if not self._api_key or not self._folder_id:
            raise RuntimeError("YANDEX_API_KEY/YANDEX_FOLDER_ID не заданы")
        model = f"gpt://{self._folder_id}/{self.cfg.model}/latest"
        prompt_user = (
            f"Заголовок: {item.title}\n\n"
            f"Текст:\n{item.text or item.html or ''}\n\n"
            f"Региональный фокус: Нижегородская область."
        )
        payload = {
            "model": model,
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_tokens,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt_user},
            ],
        }
        data = self._request(payload)
        try:
            text = (data["choices"][0]["message"]["content"] or "").strip()
        except Exception:
            raise RuntimeError("Yandex LLM: пустой ответ")
        if max_len:
            text = text[:max_len].rstrip()
        return RewriterResult(ok=True, title=item.title, text=text, provider="yandex")


__all__ = ["LLMRewriter", "LLMConfig"]


"""Telegram бот-приёмная для предложений новостей."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

import requests

from config import (
    SUGGEST_BOT_TOKEN,
    SUGGEST_HELLO,
    SUGGEST_MOD_CHAT_ID,
    SUGGEST_USE_COPY,
)

API_BASE = "https://api.telegram.org/bot{token}/{method}"
SESSION = requests.Session()


class TelegramAPIError(Exception):
    """Общее исключение для ошибок Telegram API."""


@dataclass
class RetryAfter(TelegramAPIError):
    retry_after: float
    description: str = "Too Many Requests"


def api(method: str, **params: Any) -> Dict[str, Any]:
    """Вызов метода Bot API с базовой обработкой ошибок."""

    if not SUGGEST_BOT_TOKEN:
        raise RuntimeError("SUGGEST_BOT_TOKEN не задан. Заполните конфиг перед запуском.")

    url = API_BASE.format(token=SUGGEST_BOT_TOKEN, method=method)
    try:
        response = SESSION.post(url, json=params, timeout=30)
    except requests.RequestException as exc:  # pragma: no cover - сетевые сбои
        raise TelegramAPIError(f"Не удалось выполнить запрос {method}: {exc}") from exc

    retry_after = None
    if response.status_code == 429:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        retry_after = float(payload.get("parameters", {}).get("retry_after", 1))
        raise RetryAfter(retry_after=retry_after, description=payload.get("description", ""))

    if response.status_code >= 400:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        description = payload.get("description") or response.text
        raise TelegramAPIError(f"Telegram API вернул ошибку {response.status_code}: {description}")

    try:
        data = response.json()
    except ValueError as exc:  # pragma: no cover - Telegram всегда отвечает JSON
        raise TelegramAPIError(f"Некорректный JSON от Telegram: {response.text}") from exc

    if not data.get("ok", False):
        params = data.get("parameters") or {}
        if data.get("error_code") == 429:
            retry_after = float(params.get("retry_after", 1))
            raise RetryAfter(retry_after=retry_after, description=data.get("description", ""))
        raise TelegramAPIError(data.get("description", "Неизвестная ошибка Telegram API"))

    return data.get("result", {})


def send(chat_id: int | str, text: str) -> Dict[str, Any]:
    """Отправка текстового сообщения пользователю."""

    return api("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML")


def forward(to_chat: int | str, from_chat: int | str, msg_id: int) -> Dict[str, Any]:
    """Переслать или скопировать сообщение в модераторский чат."""

    if SUGGEST_USE_COPY:
        return api(
            "copyMessage",
            chat_id=to_chat,
            from_chat_id=from_chat,
            message_id=msg_id,
        )
    return api(
        "forwardMessage",
        chat_id=to_chat,
        from_chat_id=from_chat,
        message_id=msg_id,
    )


def _is_deep_start(text: Optional[str]) -> bool:
    if not text:
        return False
    cleaned = text.strip()
    if not cleaned.startswith("/start"):
        return False
    parts = cleaned.split(maxsplit=1)
    return len(parts) == 2 and parts[1].lower() == "suggest"


def _ack_user(chat_id: int | str, text: str) -> None:
    try:
        send(chat_id, text)
    except RetryAfter as exc:
        logging.warning("Отложенная отправка пользователю %s (retry_after=%s)", chat_id, exc.retry_after)
        time.sleep(exc.retry_after)
        send(chat_id, text)
    except TelegramAPIError:
        logging.exception("Не удалось отправить сообщение пользователю %s", chat_id)


def _handle_message(message: Dict[str, Any]) -> None:
    message_id = message.get("message_id")
    if not message_id:
        logging.debug("Пропущено сообщение без message_id: %s", message)
        return

    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id:
        logging.debug("Пропущено сообщение без chat.id: %s", message)
        return

    text = message.get("text") if isinstance(message.get("text"), str) else None
    if _is_deep_start(text):
        logging.info("Получена команда /start suggest от %s", chat_id)
        _ack_user(chat_id, SUGGEST_HELLO)
        return

    if not SUGGEST_MOD_CHAT_ID:
        logging.error("SUGGEST_MOD_CHAT_ID не настроен. Сообщение от %s не переслано.", chat_id)
        _ack_user(chat_id, "⚠️ Бот временно недоступен, попробуйте позже.")
        return

    try:
        forward(SUGGEST_MOD_CHAT_ID, chat_id, message_id)
    except RetryAfter as exc:
        wait = max(exc.retry_after, 1.0)
        logging.warning(
            "Пересылка сообщения %s отклонена Telegram (retry_after=%s).", message_id, wait
        )
        time.sleep(wait)
        forward(SUGGEST_MOD_CHAT_ID, chat_id, message_id)
    except TelegramAPIError:
        logging.exception("Не удалось переслать сообщение %s", message_id)
        _ack_user(chat_id, "⚠️ Не удалось отправить заявку, попробуйте позже.")
        return

    _ack_user(chat_id, "✅ Заявка отправлена модераторам")


def _process_update(update: Dict[str, Any]) -> None:
    message = update.get("message") or update.get("channel_post")
    if not isinstance(message, dict):
        logging.debug("Пропущено обновление без message/channel_post: %s", update)
        return
    _handle_message(message)


COMMANDS_PAYLOAD: list[dict[str, str]] = [
    {"command": "start", "description": "Запуск подачи новости"},
    {"command": "help", "description": "Краткая инструкция"},
    {"command": "privacy", "description": "Как обрабатываются данные"},
    {"command": "cancel", "description": "Отменить текущий шаг"},
]


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    offset = None
    backoff = 1.0
    allowed_updates: Iterable[str] = ("message", "channel_post")

    logging.info("Бот-приёмная запущен. Ожидание обновлений...")
    while True:
        try:
            params: Dict[str, Any] = {"timeout": 50, "allowed_updates": list(allowed_updates)}
            if offset is not None:
                params["offset"] = offset
            updates = api("getUpdates", **params)
            backoff = 1.0
        except RetryAfter as exc:
            wait = max(exc.retry_after, backoff)
            logging.warning("Превышен лимит запросов. Повтор через %.1f с", wait)
            time.sleep(wait)
            backoff = min(backoff * 2, 60.0)
            continue
        except TelegramAPIError:
            logging.exception("Ошибка при получении обновлений")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60.0)
            continue

        if isinstance(updates, list):
            for update in updates:
                update_id = update.get("update_id")
                if update_id is not None:
                    offset = update_id + 1
                try:
                    _process_update(update)
                except TelegramAPIError:
                    logging.exception("Ошибка обработки обновления: %s", update)
                except Exception:  # pragma: no cover - защищает от неожиданных ошибок
                    logging.exception("Непредвиденная ошибка при обработке: %s", update)
        else:
            logging.debug("Ответ getUpdates не список: %s", updates)

        time.sleep(0.5)


if __name__ == "__main__":
    main()

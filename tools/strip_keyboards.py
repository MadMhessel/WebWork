import os
import time
import requests

TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["MOD_CHAT_ID"]
MESSAGE_IDS = []  # заполните идентификаторами сообщений предпросмотра с кнопками


def api(method: str, **payload):
    response = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/{method}",
        data=payload,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


for message_id in MESSAGE_IDS:
    api(
        "editMessageReplyMarkup",
        chat_id=CHAT_ID,
        message_id=message_id,
        reply_markup='{"inline_keyboard": []}',
    )
    time.sleep(0.05)

import os
import time
import requests

TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["MOD_CHAT_ID"]  # id модераторского чата

# id сообщений модераторского превью, нужно заполнить перед запуском
MESSAGE_IDS: list[int] = []  # заполнить при запуске / или получить из своего storage


def api(method: str, **payload):
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/{method}", data=payload, timeout=30
    )
    r.raise_for_status()
    return r.json()


def strip(mid: int):
    # Пустая разметка => удалит кнопки у сообщения
    api(
        "editMessageReplyMarkup",
        chat_id=CHAT_ID,
        message_id=mid,
        reply_markup='{"inline_keyboard": []}',
    )


if __name__ == "__main__":
    for mid in MESSAGE_IDS:
        try:
            strip(mid)
            time.sleep(0.05)
        except Exception as exc:  # pragma: no cover - utility script logging
            print("fail:", mid, exc)

# newsbot — агрегатор новостей о стройке в Нижегородской области

Собирает новости из источников (RSS/HTML), фильтрует строго по двум осям (**Нижегородская область** И **строительство**), удаляет дубликаты и публикует в Telegram-канал.

## Установка и зависимости
Python 3.10+
```bash
pip install -r requirements.txt
# при необходимости HTML-парсинга:
pip install beautifulsoup4
```

## Настройка
Настройка выполняется один раз через `.env` в директории профиля пользователя
(`%APPDATA%/NewsBot/.env` на Windows). Создать файл можно командой:

```bash
python -m config init
```

Можно также скопировать шаблон `.env.example` и заполнить его.

Поддерживаются следующие переменные:
- `BOT_TOKEN`, `CHANNEL_ID`, `REVIEW_CHAT_ID`, `CHANNEL_CHAT_ID`
- `MODERATOR_IDS`, `ATTACH_IMAGES`, `MAX_MEDIA_PER_POST`, `IMAGE_MIN_EDGE`, `IMAGE_MIN_AREA`, `IMAGE_DOMAINS_DENYLIST`
- `SNOOZE_MINUTES`, `REVIEW_TTL_HOURS`, `RETRY_LIMIT`
- `ENABLE_REWRITE`, `STRICT_FILTER`, `LOG_LEVEL`
- `ON_SEND_ERROR`, `PUBLISH_MAX_RETRIES`, `RETRY_BACKOFF_SECONDS`
- `POLL_INTERVAL_SECONDS`, `FETCH_LIMIT_PER_SOURCE`
- `HTTP_TIMEOUT_CONNECT`, `HTTP_TIMEOUT_READ`, `HTTP_RETRY_TOTAL`, `HTTP_BACKOFF`
- `IMAGE_ALLOWED_EXT`, `IMAGE_DENYLIST_DOMAINS`, `MIN_IMAGE_BYTES`
- ключевые слова и источники в `newsbot/config.py`

В блоке `SOURCES` у каждого источника теперь есть флаг `enabled` и опциональные
поля `timeout`/`retry` для индивидуальных сетевых настроек.

## Запуск
Разово:
```bash
python -m newsbot.main --once
```
Цикл:
```bash
python -m newsbot.main --loop
```
DRY-RUN + мок-набор:
```bash
python -m newsbot.main --once --dry-run --mock
```

## Формат логов
`YYYY-MM-DD HH:MM:SS | LEVEL | logger | message` — решения по каждой новости: `[SKIP]`, `[DUP-DB]`, `[DRY-RUN: READY]`, `[PUBLISHED]`.

## Ограничения Telegram
Лимит 4096 символов; бот экранирует разметку и сокращает тело, не повреждая формат.

## Антидубликаты
SQLite `published_news`: UNIQUE url, индексы по `guid` и `title_norm_hash`. Повторные прогоны не шлют дубли.

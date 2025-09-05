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
Через `.env` (см. `.env.example`) или переменные окружения:
- `BOT_TOKEN`, `CHANNEL_ID`
- `ENABLE_REWRITE`, `STRICT_FILTER`, `LOG_LEVEL`
- `ON_SEND_ERROR`, `PUBLISH_MAX_RETRIES`, `RETRY_BACKOFF_SECONDS`
- `POLL_INTERVAL_SECONDS`, `FETCH_LIMIT_PER_SOURCE`
- ключевые слова и источники в `newsbot/config.py`

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

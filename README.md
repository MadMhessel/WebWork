# newsbot — агрегатор новостей о стройке в Нижегородской области

Собирает новости из источников (RSS/HTML), фильтрует по региональным ключевым словам. Тематика строительства учитывается как дополнительный критерий, помогает выделять профильные материалы, но не является обязательной. Удаляет дубликаты и публикует сообщения в Telegram-канал.

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

По умолчанию достаточно присутствия региональных ключевых слов. Если установить `STRICT_FILTER=1`, бот будет требовать одновременно и регион, и строительную тематику.

Переменные `CHANNEL_ID`/`CHANNEL_CHAT_ID` и `REVIEW_CHAT_ID` должны быть заполнены
реальными идентификаторами каналов или чатов. Иначе попытка отправить сообщение
в Telegram завершится ошибкой вида `Bad Request: chat not found`.

В блоке `SOURCES` у каждого источника теперь есть флаг `enabled` и опциональные
поля `timeout`/`retry` для индивидуальных сетевых настроек.

## Запуск
Разово:
```bash
python main.py
```
Цикл:
```bash
python main.py --loop
```

## Запуск через PowerShell
Полный пример для Windows:

```powershell
# клонирование и переход в каталог проекта
git clone <URL_репозитория>
cd WebWork

# при желании создаём виртуальное окружение
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1

# установка зависимостей
pip install -r requirements.txt

# однократная инициализация конфигурации (.env создастся в профиле пользователя)
python -m config init

# запуск одного прохода
python .\main.py

# запуск в бесконечном цикле
python .\main.py --loop
```

## Формат логов
`YYYY-MM-DD HH:MM:SS | LEVEL | logger | message` — решения по каждой новости: `[SKIP]`, `[DUP-DB]`, `[DRY-RUN: READY]`, `[PUBLISHED]`.

## Ограничения Telegram
Лимит 4096 символов; бот экранирует разметку и сокращает тело, не повреждая формат.

## Антидубликаты
SQLite `published_news`: UNIQUE url, индексы по `guid` и `title_norm_hash`. Повторные прогоны не шлют дубли.

# WebWork — агрегатор новостей и Telegram-постов

Сервис строит ленту новостей о строительстве в Нижегородской области. Источники
подключаются по RSS/HTML и через официальное API Telegram. Лента проходит через
этапы фильтрации, тегирования, дедупликации, рерайта, модерации и публикации в
каналы Telegram.

Архитектура пайплайна:

```
fetcher → filters/tagging/classifieds → dedup → rewrite → moderation → publisher
```

Дополнительно работает «сырая» ветка (`RAW`), которая собирает материалы в
обход фильтров для ручного просмотра.

## Требования

* Python 3.10+
* Telegram Bot API токен (`TELEGRAM_BOT_TOKEN`)
* Доступ к официальному API Telegram (MTProto) — `api_id`, `api_hash`, файл
  сессии Telethon
* SQLite (входит в стандартную библиотеку Python)
* Дополнительные библиотеки из `requirements.txt`

Установка зависимостей:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Для резервного HTML-парсинга установите `beautifulsoup4`:

```bash
pip install beautifulsoup4
```

## Подготовка Telegram API (MTProto)

1. Авторизуйтесь на [my.telegram.org](https://my.telegram.org).
2. В разделе **API development tools** создайте приложение и получите
   `api_id` и `api_hash`.
3. Укажите их в `.env` вместе с именем сессии Telethon (по умолчанию
   `webwork_telethon`). Файл сессии Telethon появится рядом со стартовым
   скриптом после первого запуска.
4. При работе из контейнера сохраните `.session` в `./sessions` или рядом с
   исходниками и добавьте путь в `TELETHON_SESSION_NAME` при необходимости.

## Настройка окружения

Конфигурация загружается из `~/.config/NewsBot/.env` (Linux/macOS) или
`%APPDATA%/NewsBot/.env` (Windows). Локальный `.env` рядом с исходниками
используется только для разработки и не должен попадать в VCS.

Основные переменные:

| Переменная | Обязательно | Значение по умолчанию | Описание |
| --- | --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` (`BOT_TOKEN`) | да | — | Токен Telegram Bot API |
| `CHANNEL_TEXT_CHAT_ID` | да | `CHANNEL_CHAT_ID` | Канал для длинных текстов (sendMessage) |
| `CHANNEL_MEDIA_CHAT_ID` | да | `CHANNEL_CHAT_ID` | Канал для медиа (sendPhoto/sendVideo) |
| `ENABLE_TEXT_CHANNEL` | нет | `1` | Управляет отправкой в текстовый канал |
| `ENABLE_MEDIA_CHANNEL` | нет | `1` | Управляет отправкой в медиа-канал |
| `ONLY_TELEGRAM` | нет | `0` | Включает режим сбора только из Telegram |
| `TELEGRAM_MODE` | нет | `mtproto` | Режим сбора (`mtproto` или `web`) |
| `TELEGRAM_LINKS_FILE` | нет | `telegram_links.txt` | Список каналов для основной ленты |
| `TELEGRAM_FETCH_LIMIT` | нет | `30` | Кол-во сообщений на канал |
| `TELETHON_API_ID` | да при `mtproto` | — | `api_id` из my.telegram.org |
| `TELETHON_API_HASH` | да при `mtproto` | — | `api_hash` из my.telegram.org |
| `TELETHON_SESSION_NAME` | нет | `webwork_telethon` | Имя файла сессии Telethon |
| `DRY_RUN` | нет | `0` | Не отправляет сообщения, только логирует |
| `ENABLE_MODERATION` | нет | `0` | Включает ручную модерацию |
| `REVIEW_CHAT_ID` | да при модерации | — | Чат для модераторов |
| `RAW_STREAM_ENABLED` | нет | `0` | Активирует RAW-пайплайн |
| `RAW_REVIEW_CHAT_ID` | нет | `REVIEW_CHAT_ID` | Куда отправлять RAW |
| `RAW_BYPASS_FILTERS` | нет | `0` | Отключает фильтры в RAW |
| `RAW_BYPASS_DEDUP` | нет | `0` | Отключает дедупликацию в RAW |
| `RAW_FORWARD_STRATEGY` | нет | `copy` | `copy`, `forward` или `link` |
| `HTTP_TIMEOUT_READ` | нет | `10` | Таймаут чтения HTTP (сек) |
| `HTTP_TIMEOUT_CONNECT` | нет | `5` | Таймаут соединения (сек) |
| `HTTP_RETRY_TOTAL` | нет | `3` | Повторы при ошибках 429/5xx |
| `HTTP_BACKOFF` | нет | `0.5` | Коэффициент экспоненциальной паузы |
| `LOG_LEVEL` | нет | `INFO` | Уровень логирования |

Дополнительные переменные описаны в коде (`config.py`, `webwork/config.py`).

### Профили конфигурации

Для быстрого переключения режимов используйте файл `profiles.yaml`. Укажите имя
профиля в переменной окружения `NEWSBOT_PROFILE` (или `NEWSBOT_MODE`), чтобы
подставить набор переменных перед запуском пайплайна. Файл ищется в
`~/.config/NewsBot/profiles.yaml`, рядом с исходниками или в пути из
`NEWSBOT_PROFILE_PATH`.

Пример запуска режима только Telegram:

```bash
NEWSBOT_PROFILE=telegram-only python main.py
```

Любые переменные, указанные напрямую в окружении или `.env`, имеют приоритет
над значениями из профиля. Чтобы принудительно перезаписать конкретное
значение, воспользуйтесь расширенной формой в `profiles.yaml`:

```yaml
lightweight:
  extends: default
  settings:
    FETCH_LIMIT_PER_SOURCE:
      value: 10
      override: true
```

## Файлы ссылок

* `telegram_links.txt` — основной список каналов. Формат: одна ссылка вида
  `https://t.me/<alias>` или `https://t.me/s/<alias>` на строку. Префикс `/s/`
  автоматически удаляется. Комментарии, начинающиеся с `#`, игнорируются.
* `telegram_links_raw.txt` — источники для RAW-потока. Обрабатывается отдельно
  и не смешивается с основной лентой.

## Режимы: основная лента и RAW

* **Основная лента** — проходит все этапы пайплайна, публикуется в рабочие
  каналы (`CHANNEL_TEXT_CHAT_ID`, `CHANNEL_MEDIA_CHAT_ID`). При `ONLY_TELEGRAM=1`
  источники из RSS/HTML игнорируются.
* **RAW** — независимый поток для ревью. Использует отдельный файл ссылок,
  публикует только в `RAW_REVIEW_CHAT_ID`, может обходить фильтры и
  дедупликацию (`RAW_BYPASS_FILTERS`, `RAW_BYPASS_DEDUP`). Стратегия
  доставки регулируется `RAW_FORWARD_STRATEGY`: `copy`, `forward` или `link`.

## Запуск

### Linux/macOS

```bash
python -m config init            # однократно, создаёт ~/.config/NewsBot/.env
python main.py                   # основная лента
python raw_pipeline.py           # при необходимости запустить RAW отдельно
```

### Интерактивный запуск и настройка

Для удобной смены ключей и переменных окружения используйте интерактивный
интерфейс `tools/launcher.py`:

```bash
python -m tools.launcher
```

Скрипт предложит ввести токены и ID каналов, подскажет доступные профили из
`profiles.yaml`, сохранит значения в `~/.config/NewsBot/.env` и запустит
указанный скрипт (по умолчанию `main.py`). Чтобы запустить RAW-пайплайн через
интерфейс, передайте имя скрипта:

```bash
python -m tools.launcher --script raw_pipeline.py
```

Дополнительные переменные можно передавать флагом `--set`, например
`--set DRY_RUN=1 LOG_LEVEL=DEBUG`.

### Windows

Используйте `start.bat` или вручную активируйте виртуальное окружение:

```bat
python -m venv .venv
.venv\Scripts\activate
python -m config init
python main.py
```

## Публикация в два канала

Публикация выполняется функцией `publisher.publish_post`, которая маршрутизирует
сообщения через `webwork.router.route_and_publish`:

* текстовые материалы отправляются методом `sendMessage` в канал
  `CHANNEL_TEXT_CHAT_ID` с разбивкой по 4096 символов;
* сообщения с медиа используют `sendPhoto` или `sendVideo`. Подпись
  ограничивается 1024 символами, остаток текста догружается отдельными
  сообщениями;
* при отсутствии медиа происходит fallback к текстовой отправке в медиа-канал;
* при `DRY_RUN=1` все действия только логируются с префиксом `[DRY-RUN]`.

## Ограничения Telegram

* Текст сообщения — максимум 4096 символов.
* Подпись к фото/видео — максимум 1024 символа.
* MarkdownV2 требует экранирования спецсимволов (`webwork.utils.formatting`).
* Bot API ограничивает частоту запросов (используется экспоненциальный backoff).

## Тестирование и DRY-RUN

* `DRY_RUN=1` полностью отключает обращения к Bot API. Логи содержат
  `[DRY-RUN]` и фиктивные `message_id`.
* Юнит-тесты: `pytest`. Покрывают фильтры, форматирование, чанкование текстов
  и нормализацию телеграм-ссылок.
* Для проверки MTProto соберите 2–3 канала в `telegram_links.txt` и запустите:

  ```bash
  ONLY_TELEGRAM=1 TELEGRAM_MODE=mtproto DRY_RUN=1 python main.py
  ```

  Логи покажут чтение каналов, количество сообщений и попытки публикации.

## Траблшутинг

* **`Missing TELETHON_API_ID`** — переменные MTProto не заданы. Проверьте `.env`.
* **`SessionPasswordNeededError`** — аккаунт защищён 2FA. Войдите через Telethon
  (файл сессии будет создан заново).
* **`CHANNEL_CHAT_ID not found`** — укажите правильный `@alias` или числовой ID.
* **Rate limit/429** — увеличьте `HTTP_BACKOFF` или уменьшите `TELEGRAM_FETCH_LIMIT`.
* **HTML parser fails** — включите MTProto (`TELEGRAM_MODE=mtproto`) или установите
  `beautifulsoup4` для fallback-режима.
* **Логи пустые** — проверьте каталог `~/NewsBot/logs` (или путь из `LOG_DIR`/`LOG_DIR_NAME`).

## Отладка

Логи пишутся в `~/NewsBot/logs` (можно изменить через `LOG_DIR` или `LOG_DIR_NAME`,
есть fallback в `./logs`) с ротацией по размеру. Основные файлы: `app.log`,
`errors.log`, `bot.log`, `audit.log`, `sql.log` (по запросу). Уровень логов
управляется переменной `LOG_LEVEL`.

Для ручной отладки MTProto воспользуйтесь `tools/telethon_shell.py`
(запускается в виртуальном окружении и использует те же переменные окружения).

## Windows quick start

```powershell
.\scripts\setup_env.ps1
.\scripts\run.ps1
```

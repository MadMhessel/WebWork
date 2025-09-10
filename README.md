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
(`%APPDATA%/NewsBot/.env` на Windows, `~/.config/NewsBot/.env` на Linux/macOS).
Файл рядом с кодом `WebWork/.env` при наличии **переопределяет** значения из
профильного. Создать основной файл можно командой:

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
- `IMAGES_ENABLED`, `IMAGES_MAX_BYTES`, `IMAGES_MIN_WIDTH`, `IMAGES_CONVERT_TO_JPEG`,
  `IMAGES_CACHE_DIR`
- `MAX_POST_LEN`, `MAX_CAPTION_LEN`, `REWRITE_TARGET_LEN`, `REGION_HINT`,
  `PARSE_MODE`, `SPLIT_LONG_POSTS`
- `ENABLE_LLM_REWRITE`, `YANDEX_API_MODE`, `YANDEX_API_KEY`,
  `YANDEX_IAM_TOKEN`, `YANDEX_FOLDER_ID`, `YANDEX_MODEL`,
  `YANDEX_TEMPERATURE`, `YANDEX_MAX_TOKENS`
- ключевые слова и источники в `newsbot/config.py`

### Подсистема изображений

Новая архитектура обработки изображений гарантирует отправку только реальных
фото. Бот скачивает файлы локально, проверяет размеры и лицензии и использует
кэш `images_cache` с полем `created_at` для повторного использования `tg_file_id`.
Поддерживается поиск контекстных изображений из открытых источников
(Openverse, Wikimedia). Основные параметры окружения:

- `CONTEXT_IMAGE_ENABLED` — разрешить поиск контекстных фото (по умолчанию `true`)
- `CONTEXT_IMAGE_PREFERRED` — пробовать контекстные фото раньше сайта (`false`)
- `CONTEXT_IMAGE_PROVIDERS` — список провайдеров, порядок задаёт приоритет
- `CONTEXT_LICENSES` — белый список лицензий (`cc0,cc-by,cc-by-sa`)
- `ALLOW_PLACEHOLDER` и `FALLBACK_IMAGE_URL` — включение заглушки (по умолчанию выключено)

Если изображение не найдено, бот публикует сообщение без фото. В Telegram
никогда не отправляются внешние URL — используется только локальный файл или
уже сохранённый `tg_file_id`.

### Рерайт через YandexGPT

Для более качественного сжатия текста используется модель YandexGPT. Включить
её можно, задав в `.env` переменную `ENABLE_LLM_REWRITE=true` и указав
учётные данные:

```
YANDEX_API_MODE=openai  # или rest
YANDEX_API_KEY=<API-ключ>         # для режима openai
YANDEX_IAM_TOKEN=<IAM‑токен>      # для режима rest
YANDEX_FOLDER_ID=<folder-id>
```

API‑ключ создаётся в [консоли Yandex Cloud](https://console.cloud.yandex.ru/):
нужен сервисный аккаунт с ролью `ai.languageModels.user` и ключом с областью
`yc.ai.foundationModels.execute`. `FOLDER_ID` можно посмотреть на странице
каталога. Дополнительные параметры (`YANDEX_MODEL`, `YANDEX_TEMPERATURE`,
`YANDEX_MAX_TOKENS`) позволяют тонко настроить генерацию.

По умолчанию достаточно присутствия региональных ключевых слов. Если установить `STRICT_FILTER=1`, бот будет требовать одновременно и регион, и строительную тематику.

Переменные `CHANNEL_ID`/`CHANNEL_CHAT_ID` и `REVIEW_CHAT_ID` должны быть заполнены
реальными идентификаторами каналов или чатов. Иначе попытка отправить сообщение
в Telegram завершится ошибкой вида `Bad Request: chat not found`.

В блоке `SOURCES` у каждого источника теперь есть флаг `enabled` и опциональные
поля `timeout`/`retry` для индивидуальных сетевых настроек.

## Быстрый старт
1. Скопируйте `.env.example` в профиль пользователя:
   ```bash
   cp WebWork/.env.example ~/.config/NewsBot/.env  # для Windows путь %APPDATA%/NewsBot/.env
   ```
2. Укажите в файле обязательные параметры:
   - `TELEGRAM_BOT_TOKEN` – токен бота;
   - `CHANNEL_CHAT_ID` (или `CHANNEL_ID`) – целевой канал;
   - при модерации (`ENABLE_MODERATION=1`) задайте `REVIEW_CHAT_ID` и `MODERATOR_IDS`.
3. При необходимости скорректируйте лимиты Telegram и параметры изображений
   (`CAPTION_LIMIT`, `TELEGRAM_MESSAGE_LIMIT`, `ATTACH_IMAGES`, `FALLBACK_IMAGE_URL`).
4. Запустите `python main.py`.

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

## Схема пайплайна

1. **Фильтрация** — новости отбрасываются, если не содержат упоминаний
   Нижегородской области.
2. **Изображения** — модуль `images` выбирает лучшую картинку, скачивает и
   кэширует её в каталоге `./cache/images`.  Файлы меньшие 20 KB или шириной
   менее 400 px отбрасываются.
3. **Рерайт** — `rewriter.Rewriter` формирует укороченный безопасный текст.
   Вначале пробуется внешняя LLM, при ошибке используется правило‑ориентированная
   стратегия.  Длина поста ограничивается `MAX_POST_LEN`.
4. **Публикация** — через `telegram_client` отправляется фотография с кратким
   caption и затем при необходимости длинный текст.

## Антидубликаты
SQLite `published_news`: UNIQUE url, индексы по `guid` и `title_norm_hash`. Повторные прогоны не шлют дубли.

## Модерация
Если `ENABLE_MODERATION=1`, каждое сообщение сначала попадает в чат ревью `REVIEW_CHAT_ID`.
В превью используются inline-кнопки:

- `✅ Утвердить` — мгновенная публикация.
- `📝 Заголовок`, `📝 Текст`, `🏷️ Теги` — редактирование полей (ForceReply).
- `💤 15м/1ч/3ч` — отложить запись на заданный срок.
- `🚫 Отклонить` — запрос причины и пометка в очереди.

Список модераторов задаётся через переменную окружения `MODERATOR_IDS`.
При откладывании поле `resume_at` в таблице `moderation_queue` заполняется
временем возврата в очередь.

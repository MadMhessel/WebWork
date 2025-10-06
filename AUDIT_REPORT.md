# Отчет об аудите проекта WebWork

## 1. Назначение системы
WebWork — агрегатор новостей и Telegram-постов для ленты о строительстве в
Нижегородской области. Он собирает контент по RSS/HTML и через официальное API
Telegram, затем прогоняет его через фильтрацию, тегирование, дедупликацию,
рерайт, модерацию и публикацию в каналы Telegram.【F:README.md†L1-L13】

## 2. Структура пайплайна
Основной сценарий `main.py` выстраивает последовательность обработки,
опираясь на конфигурацию и внешние модули. Пайплайн включает сбор данных,
фильтрацию, категоризацию, дедупликацию, рерайт, модерацию и публикацию в
каналы, а также независимую RAW-ветку для ручной проверки материалов.【F:main.py†L1-L113】【F:README.md†L9-L48】

## 3. Ключевые компоненты
- **Сбор**: модуль `fetcher.fetch_all` объединяет RSS/HTML-источники, а
  `telegram_fetcher.fetch_from_telegram` обеспечивает сбор через Bot API и
  MTProto в зависимости от настроек `TELEGRAM_MODE`. Источники описаны в
  `sources.py` и YAML-конфигурациях.【F:main.py†L67-L105】【F:sources.py†L1-L120】【F:sources_nn.yaml†L1-L120】
- **Фильтрация и категоризация**: `filters.is_relevant_for_source`,
  `tagging.extract_tags` и модуль `classifieds` отсеивают нерелевантные и
  рекламные сообщения перед дальнейшей обработкой.【F:main.py†L106-L156】【F:filters.py†L1-L180】【F:tagging.py†L1-L200】
- **Дедупликация**: `dedup` и `utils.compute_title_hash` устраняют повторы по
  URL и заголовкам, предотвращая повторную публикацию контента.【F:main.py†L145-L188】【F:dedup.py†L1-L220】【F:utils.py†L1-L200】
- **Рерайт**: модули `rewrite` и пакет `autorewrite/` готовят текст к
  публикации, обрабатывая формулировки и форматирование, а также поддерживают
  альтернативные сценарии fallback через `rewriter_module.py`.【F:rewrite.py†L1-L200】【F:autorewrite/__init__.py†L1-L160】【F:rewriter_module.py†L1-L220】
- **Модерация**: `moderation`, `moderator` и очередь в `moderation.yaml`
  реализуют ручную проверку, а `raw_pipeline.py` обслуживает RAW-поток для
  ревью, включая кастомные списки каналов и обход фильтров при необходимости.【F:moderation.py†L1-L220】【F:moderator.py†L1-L200】【F:raw_pipeline.py†L1-L220】
- **Публикация**: `publisher.publish_structured_item` и пакет `webwork/`
  (включая `router.py` и `publisher.py`) маршрутизируют сообщения в текстовый и
  медиа-каналы Telegram с учетом ограничений Bot API и настроек DRY-RUN.【F:main.py†L25-L66】【F:webwork/publisher.py†L1-L200】【F:webwork/router.py†L1-L200】

## 4. Конфигурация и внешние данные
- Основные настройки загружаются из `config.py` и `config_defaults.py`, которые
  поддерживают режимы `ONLY_TELEGRAM`, `RAW_STREAM_ENABLED` и связные параметры.
- Файлы `telegram_links.txt` и `telegram_links_raw.txt` задают списки каналов
  для основной и RAW-веток соответственно, а `tag_rules.yaml` и
  `moderation.yaml` описывают правила тегирования и ручной модерации.【F:config.py†L1-L320】【F:config_defaults.py†L1-L200】【F:telegram_links.txt†L1-L200】【F:telegram_links_raw.txt†L1-L200】【F:tag_rules.yaml†L1-L120】【F:moderation.yaml†L1-L120】

## 5. Проверка работоспособности
Полный набор автоматических тестов `pytest` успешно проходит (91 тест).
Команда выполнялась из корня репозитория и подтверждает работоспособность
пайплайна, парсеров, форматирования, модерации и телеграмных интеграций на
уровне модульных тестов.【3447b6†L1-L30】

## 6. Рекомендации по дальнейшему контролю
1. Включить регулярный прогон `pytest` в CI, чтобы гарантировать целостность
   пайплайна перед деплоем.
2. Контролировать актуальность списков Telegram-каналов и YAML-конфигураций,
   поскольку они напрямую влияют на охват и точность фильтрации.
3. Периодически проверять `requirements.txt` на обновления библиотек для
   поддержания безопасности и совместимости.

## 7. Диагностика запуска `--loop`

### 7.1. Ключевые файлы и их назначение
- `main.py` — точка входа, собирающая пайплайн, поддерживающая одиночный и
  бесконечный режимы работы, а также RAW-поток.【F:main.py†L1-L244】【F:main.py†L327-L454】
- `telegram_mtproto.py` — загрузка сообщений через Telethon, требует валидных
  `TELETHON_API_ID`, `TELETHON_API_HASH` и `.session` с именем из
  `TELETHON_SESSION_NAME`.【F:telegram_mtproto.py†L1-L137】
- `publisher.py` — отправка в Telegram Bot API с экспоненциальным бэкоффом и
  fallback-стратегиями RAW-публикаций.【F:publisher.py†L1-L160】【F:publisher.py†L185-L275】
- `dedup.py` — нормализация URL, построение ключей и хранение дублей в памяти и
  SQLite, что позволяет агрессивно отсекать повторяющиеся элементы.【F:dedup.py†L1-L160】【F:dedup.py†L161-L240】
- `moderation.py` — загрузка YAML-правил блокировок, флагов и модерационных
  вердиктов, влияющих на пропуск сообщений без ошибок.【F:moderation.py†L1-L160】【F:moderation.py†L161-L240】
- `profiles.yaml` — преднастройки режимов (по умолчанию задержка цикла 600 с,
  включены модерация и рерайт).【F:profiles.yaml†L1-L40】
- `sources_nn.yaml` и `telegram_links.txt` — основной пул источников и Telegram
  каналов; отсутствие записей приводит к пустой выдаче.【F:sources_nn.yaml†L1-L120】【F:telegram_links.txt†L1-L40】
- `requirements.txt` — список зависимостей (Telethon, dotenv и т.д.),
  устанавливаемых через стартовые скрипты.【F:requirements.txt†L1-L12】【F:start.sh†L1-L48】
- `start.sh` и `start.bat` — создают/активируют `.venv`, ставят зависимости и
  запускают `python main.py ...` из корня репозитория, без модульного
  entrypoint.【F:start.sh†L1-L52】【F:start.bat†L1-L84】

### 7.2. Модульный запуск и текущая команда
Требуемая команда `python -m webwork.main --loop` завершается ошибкой `No module
named webwork.main`, поскольку пакет `webwork` не содержит `main.py` или
`__main__.py`. Текущий рабочий сценарий — прямой запуск `python main.py --loop`
из корня репозитория или через стартовые скрипты.【c5c8da†L1-L3】【F:webwork/__init__.py†L1-L42】【F:start.sh†L45-L52】

### 7.3. Проверка конфигурации `.env`
`config.validate_config()` падает с `Missing config: TELEGRAM_BOT_TOKEN,
REVIEW_CHAT_ID`, подтверждая отсутствие ключевых переменных. Функция также
требует `CHANNEL_CHAT_ID`, `MODERATOR_IDS` и MTProto-креды при `ONLY_TELEGRAM` и
`TELEGRAM_MODE=mtproto`, а `.env` хранится в `~/.config/NewsBot/.env`. Для MTProto
необходима валидная `.session`, имя которой задаётся `TELETHON_SESSION_NAME`.【71132f†L1-L8】【F:config.py†L394-L456】【F:README.md†L40-L75】

### 7.4. Мини-прогон `--once`
Попытка `WEBWORK_LOG_LEVEL=DEBUG python main.py --once` останавливается на
валидации конфигурации, поэтому конвейер не доходит до этапов `fetch → parse →
filters → dedup → rewrite → moderation → publish`. После заполнения `.env`
следует отслеживать логи: `Загрузка из Telegram` (fetch), `[SKIP]`/`[DUP_DB]`
(filters/dedup), `[BLOCK]`/`needs_confirmation` (moderation) и `RAW:` (RAW-поток).
При `fetch` с нулевым результатом — вероятно пустые источники или отсутствие
MTProto-сессии.【ea5e63†L1-L11】【F:main.py†L111-L240】【F:main.py†L241-L344】【F:raw_pipeline.py†L1-L120】

### 7.5. FloodWait и Telethon
Обработчики Telethon ловят общие `RPCError`, но не содержат `sleep`/бэкоффа для
`FloodWaitError`, поэтому при превышении лимитов Telethon завершится без
ожидания. Требуется добавить явный `sleep(exc.seconds)` либо экспоненциальный
бэкофф в `_fetch_alias` или `fetch_bulk_channels`.【F:telegram_mtproto.py†L69-L115】【F:teleapi_client.py†L47-L103】

### 7.6. Отчёт (A/B/C)
**A. Вероятные причины «цикл не крутится» (по убыванию):**
1. Отсутствует модульный entrypoint `webwork.main`, поэтому `python -m
   webwork.main --loop` падает до запуска цикла.【c5c8da†L1-L3】【F:webwork/__init__.py†L1-L42】
2. Запуск вне корня или без активированного `.venv`: стартовые скрипты всегда
   переходят в корень и вызывают `python main.py`, ручной запуск из другого
   каталога не найдёт модули/`.env`.【F:start.sh†L1-L52】【F:start.bat†L1-L84】
3. Пустой `.env` или отсутствие `.session`: валидация требует токена бота,
   идентификаторов каналов, MTProto-кредов и модераторских параметров; без них
   приложение завершается на старте.【71132f†L1-L8】【F:config.py†L394-L456】【F:README.md†L40-L75】
4. Агрессивный дедупликатор: совпадение URL/хеша/заголовка приводит к тихому
   пропуску элементов, что создаёт впечатление «цикл пустой».【F:main.py†L139-L214】【F:dedup.py†L107-L198】
5. Строгая модерация/флаги: блоклисты и hold-флаги отклоняют материалы без
   ошибок, перенося их в очередь либо отбрасывая.【F:main.py†L205-L279】【F:moderation.py†L1-L160】
6. RAW-режим без источников: при `RAW_STREAM_ENABLED=1` и пустом списке RAW
   публикации пропускаются, логируя только предупреждения.【F:main.py†L73-L134】【F:raw_pipeline.py†L1-L120】

**B. Чек-лист запуска (Linux/macOS и Windows):**
```
# Linux/macOS
cd /path/to/WebWork
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m config init              # создаст ~/.config/NewsBot/.env при отсутствии
nano ~/.config/NewsBot/.env        # заполнить TELEGRAM_BOT_TOKEN, CHANNEL_CHAT_ID,
                                  # REVIEW_CHAT_ID, MODERATOR_IDS, Telethon api_id/api_hash
cp telegram_links.txt.sample telegram_links.txt  # при необходимости
python main.py --once              # проверка конвейера (до исправления entrypoint)
python main.py --loop              # действующая команда
```
```
:: Windows (PowerShell аналогично через start.bat)
cd C:\path\to\WebWork
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python -m config init
notepad %APPDATA%\NewsBot\.env    :: заполнить токен бота, chat_id, MTProto ключи
copy telegram_links.txt.sample telegram_links.txt
python main.py --once
python main.py --loop
```

**C. Мини-тесты:**
- `python -m webwork.main --help` — сейчас падает с `No module named webwork.main`,
  подтверждая отсутствие entrypoint (ожидаемый результат до фикса).【c5c8da†L1-L3】
- `python - <<'PY' ... config.validate_config()` — показывает список
  недостающих переменных; при корректной настройке должен выводить `OK`.【71132f†L1-L8】【F:config.py†L394-L456】
- `python - <<'PY' ... _load_aliases('telegram_links.txt')` — проверяет, что
  основная матрица каналов загружена (в репозитории найдено 42 alias).【4227a8†L1-L7】【F:telegram_mtproto.py†L31-L63】
- `WEBWORK_LOG_LEVEL=DEBUG python main.py --once` — после заполнения `.env`
  позволяет увидеть, на каком этапе пайплайна происходит отбор элементов; до
  заполнения завершается на валидации конфигурации.【ea5e63†L1-L11】【F:main.py†L111-L344】


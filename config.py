import os
from urllib.parse import urlparse
from pathlib import Path

from dotenv import load_dotenv
from platformdirs import user_config_dir

try:  # pragma: no cover - список источников региона
    from sources_nn import SOURCES_NN, SOURCES_BY_DOMAIN, SOURCES_BY_ID
except Exception:  # pragma: no cover - файл может отсутствовать
    SOURCES_NN: list[dict] = []
    SOURCES_BY_DOMAIN: dict[str, list[dict]] = {}
    SOURCES_BY_ID: dict[str, dict] = {}


# Load environment variables from user configuration directory and optional local .env
APP_NAME = "NewsBot"
CONFIG_DIR = Path(user_config_dir(APP_NAME))
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
ENV_PATH = CONFIG_DIR / ".env"

# First load persistent config, then allow local .env to override for development
load_dotenv(ENV_PATH)
load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

# Load hard-coded defaults if available
try:  # pragma: no cover - simple fallback handling
    from config_defaults import (
        BOT_TOKEN as DEFAULT_BOT_TOKEN,
        CHANNEL_ID as DEFAULT_CHANNEL_ID,
        ENABLE_MODERATION as DEFAULT_ENABLE_MODERATION,
        REVIEW_CHAT_ID as DEFAULT_REVIEW_CHAT_ID,
        MODERATOR_IDS as DEFAULT_MODERATOR_IDS,
    )
except Exception:  # pragma: no cover - executed only when defaults missing
    DEFAULT_BOT_TOKEN = ""
    DEFAULT_CHANNEL_ID = ""
    DEFAULT_ENABLE_MODERATION = False
    DEFAULT_REVIEW_CHAT_ID = ""
    DEFAULT_MODERATOR_IDS: set[int] = set()

# === Базовые настройки бота ===
# Support both legacy names and new explicit TELEGRAM_* variables
BOT_TOKEN: str = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("BOT_TOKEN", DEFAULT_BOT_TOKEN)
).strip()
CHANNEL_ID: str = os.getenv("CHANNEL_ID", DEFAULT_CHANNEL_ID).strip()  # пример: "@my_news_channel" или числовой ID
RETRY_LIMIT: int = int(os.getenv("RETRY_LIMIT", "3"))

# === Бот-приёмная для предложений новостей ===
SUGGEST_BOT_TOKEN: str = os.getenv("SUGGEST_BOT_TOKEN", "").strip()
_RAW_SUGGEST_CHAT = os.getenv("SUGGEST_MOD_CHAT_ID", "").strip()
SUGGEST_MOD_CHAT_ID: str | int = int(_RAW_SUGGEST_CHAT) if _RAW_SUGGEST_CHAT.lstrip("-+").isdigit() else _RAW_SUGGEST_CHAT
SUGGEST_USE_COPY: bool = os.getenv("SUGGEST_USE_COPY", "false").lower() in {"1", "true", "yes"}
SUGGEST_HELLO: str = (
    os.getenv(
        "SUGGEST_HELLO",
        (
            "👋 Здравствуйте! Пришлите текст, фото/видео, ссылку или документ. "
            "Добавьте объект/адрес и контакт для уточнений — по желанию."
        ),
    )
    .strip()
)

# === HTTP-клиент ===
HTTP_TIMEOUT_CONNECT: float = float(os.getenv("HTTP_TIMEOUT_CONNECT", "5"))
# ТЗ: connect=5s, read=65s (long-poll up to 30s)
HTTP_TIMEOUT_READ: float = float(os.getenv("HTTP_TIMEOUT_READ", "65"))
HTTP_RETRY_TOTAL: int = int(os.getenv("HTTP_RETRY_TOTAL", "3"))
HTTP_BACKOFF: float = float(os.getenv("HTTP_BACKOFF", "0.5"))
SSL_NO_VERIFY_HOSTS: set[str] = {
    h.strip().lower()
    for h in os.getenv("SSL_NO_VERIFY_HOSTS", "").split(",")
    if h.strip()
}
TELEGRAM_LONG_POLL: int = int(os.getenv("TELEGRAM_LONG_POLL", "30"))

# === Флаги и режимы ===
ENABLE_REWRITE: bool = os.getenv("ENABLE_REWRITE", "true").lower() in {"1", "true", "yes"}
STRICT_FILTER: bool = os.getenv("STRICT_FILTER", "false").lower() in {"1", "true", "yes"}
ENABLE_MODERATION: bool = os.getenv("ENABLE_MODERATION", str(DEFAULT_ENABLE_MODERATION)).lower() in {"1", "true", "yes"}
DRY_RUN: bool = os.getenv("DRY_RUN", "false").lower() in {"1", "true", "yes"}
ADMIN_CHAT_ID: str = os.getenv("ADMIN_CHAT_ID", "").strip()
REGION_HINT: str = os.getenv("REGION_HINT", "Нижегородская область")

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_DIR_NAME: str = os.getenv("LOG_DIR_NAME", "logs").strip() or "logs"
LOG_ROTATE_BYTES: int = int(os.getenv("LOG_ROTATE_BYTES", str(10 * 1024 * 1024)))
LOG_BACKUP_COUNT: int = int(os.getenv("LOG_BACKUP_COUNT", "7"))
LOG_SQL_DEBUG: bool = os.getenv("LOG_SQL_DEBUG", "false").lower() in {"1", "true", "yes"}
LOG_TIME_ROTATE: bool = os.getenv("LOG_TIME_ROTATE", "false").lower() in {"1", "true", "yes"}
LOG_TIME_WHEN: str = os.getenv("LOG_TIME_WHEN", "midnight")
LOG_TIME_BACKUP_COUNT: int = int(os.getenv("LOG_TIME_BACKUP_COUNT", "7"))

# === Параметры модерации и медиа ===
# Allow new variable names defined in technical specification
REVIEW_CHAT_ID: str | int = (
    os.getenv("MOD_CHAT_ID")
    or os.getenv("REVIEW_CHAT_ID", DEFAULT_REVIEW_CHAT_ID)
).strip()
CHANNEL_CHAT_ID: str | int = (
    os.getenv("TARGET_CHAT_ID")
    or os.getenv("CHANNEL_CHAT_ID", CHANNEL_ID)
).strip()
MODERATOR_IDS: set[int] = {
    int(x)
    for x in (
        os.getenv("ALLOWED_MODERATORS")
        or os.getenv(
            "MODERATOR_IDS",
            ",".join(str(x) for x in DEFAULT_MODERATOR_IDS),
        )
    ).split(",")
    if x.strip()
}
ALLOWED_MODERATORS = MODERATOR_IDS
SNOOZE_MINUTES: int = int(os.getenv("SNOOZE_MINUTES", "0"))
REVIEW_TTL_HOURS: int = int(os.getenv("REVIEW_TTL_HOURS", "24"))
CAPTION_LIMIT: int = int(os.getenv("CAPTION_LIMIT", "1024"))
TELEGRAM_MESSAGE_LIMIT: int = int(os.getenv("TELEGRAM_MESSAGE_LIMIT", "4096"))
_RAW_PARSE_MODE = (
    os.getenv("TELEGRAM_PARSE_MODE")
    or os.getenv("PARSE_MODE")
    or "HTML"
)
if _RAW_PARSE_MODE.strip().lower() == "markdownv2":
    TELEGRAM_PARSE_MODE = PARSE_MODE = "MarkdownV2"
elif _RAW_PARSE_MODE.strip().lower() == "html":
    TELEGRAM_PARSE_MODE = PARSE_MODE = "HTML"
else:
    TELEGRAM_PARSE_MODE = PARSE_MODE = _RAW_PARSE_MODE.strip()
TELEGRAM_DISABLE_WEB_PAGE_PREVIEW: bool = (
    os.getenv(
        "DISABLE_WEB_PAGE_PREVIEW",
        os.getenv("TELEGRAM_DISABLE_WEB_PAGE_PREVIEW", "true"),
    )
    .lower()
    in {"1", "true", "yes"}
)

# === Регулируемые параметры фильтра ===
FILTER_HEAD_CHARS: int = int(os.getenv("FILTER_HEAD_CHARS", "400"))
WHITELIST_SOURCES = set(
    s.strip().lower()
    for s in os.getenv("WHITELIST_SOURCES", "").split(",")
    if s.strip()
)
WHITELIST_RELAX: bool = os.getenv("WHITELIST_RELAX", "true").lower() in {"1", "true", "yes"}
FETCH_LIMIT_PER_SOURCE: int = int(os.getenv("FETCH_LIMIT_PER_SOURCE", "30"))
LOOP_DELAY_SECS: int = int(os.getenv("LOOP_DELAY_SECS", "600"))

# режим «только Telegram» (ENV: ONLY_TELEGRAM=true/1/yes)
ONLY_TELEGRAM: bool = os.getenv("ONLY_TELEGRAM", "false").lower() in {"1", "true", "yes"}

# путь к списку телеграм-каналов (по одной ссылке на строку)
TELEGRAM_LINKS_FILE = os.getenv("TELEGRAM_LINKS_FILE", "telegram_links.txt").strip()

# --- Database ---
DB_PATH: str = os.getenv("DB_PATH", str(CONFIG_DIR / "newsbot.db")).strip()
ITEM_RETENTION_DAYS: int = int(os.getenv("ITEM_RETENTION_DAYS", "90"))
DEDUP_RETENTION_DAYS: int = int(os.getenv("DEDUP_RETENTION_DAYS", "45"))
DB_PRUNE_BATCH: int = int(os.getenv("DB_PRUNE_BATCH", "500"))

# --- Источники/мониторинг ---
HOST_FAIL_ALERT_THRESHOLD: int = int(os.getenv("HOST_FAIL_ALERT_THRESHOLD", "5"))
HOST_FAIL_ALERT_WINDOW_SEC: int = int(os.getenv("HOST_FAIL_ALERT_WINDOW_SEC", "1800"))
HOST_FAIL_ALERT_COOLDOWN_SEC: int = int(os.getenv("HOST_FAIL_ALERT_COOLDOWN_SEC", "900"))
SERVICE_CHAT_ID: str = os.getenv("SERVICE_CHAT_ID", os.getenv("ADMIN_CHAT_ID", "")).strip()
HOST_FAIL_AUTO_QUARANTINE_THRESHOLD: int = int(
    os.getenv("HOST_FAIL_AUTO_QUARANTINE_THRESHOLD", "3")
)
HOST_FAIL_AUTO_QUARANTINE_HOURS: float = float(
    os.getenv("HOST_FAIL_AUTO_QUARANTINE_HOURS", "4")
)


def validate_config() -> None:
    """Validate critical configuration values with clear errors."""

    missing: list[str] = []
    if not DRY_RUN and BOT_TOKEN in {"", "YOUR_TELEGRAM_BOT_TOKEN"}:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not DRY_RUN and not str(CHANNEL_CHAT_ID) and not CHANNEL_ID:
        missing.append("CHANNEL_CHAT_ID or CHANNEL_ID")
    if ENABLE_MODERATION:
        if str(REVIEW_CHAT_ID) in {"", "@your_review_channel"}:
            missing.append("REVIEW_CHAT_ID")
        if not MODERATOR_IDS:
            missing.append("MODERATOR_IDS")
    if ONLY_TELEGRAM:
        if not os.getenv("TELETHON_API_ID"):
            missing.append("TELETHON_API_ID")
        if not os.getenv("TELETHON_API_HASH"):
            missing.append("TELETHON_API_HASH")
    if missing:
        raise ValueError("Missing config: " + ", ".join(missing))
    if not isinstance(MODERATOR_IDS, set) or not all(isinstance(x, int) for x in MODERATOR_IDS):
        raise ValueError("MODERATOR_IDS must be a set[int]")
    if TELEGRAM_PARSE_MODE not in {"HTML", "MarkdownV2"}:
        raise ValueError("PARSE_MODE must be HTML or MarkdownV2")

# === Ключевые слова ===
REGION_KEYWORDS = [
    # --- Область: формы и синонимы ---
    "нижегородская область",
    "нижегородской области",
    "в нижегородской области",
    "на территории нижегородской области",
    "по нижегородской области",
    "нижегородская обл.",
    "нижегородской обл.",
    "в нижегородской обл.",
    "нижегородье",
    "нижегородск",  # стем для «нижегородский/–ая/–ом» (район, предприятия и т.п.)

    # --- Нижний Новгород (город) ---
    "нижний новгород",
    "нижнего новгорода",
    "в нижнем новгороде",
    "г. нижний новгород",
    "город нижний новгород",
    "н. новгород",
    "н.новгород",
    "н новгород",
    "нн",  # часто встречается как сокращение в лок-СМИ

    # --- Районы города Нижнего Новгорода ---
    "автозаводский район", "в автозаводском районе",
    "сормовский район", "в сормовском районе",
    "канавинский район", "в канавинском районе",
    "нижегородский район", "в нижегородском районе",
    "московский район", "в московском районе",
    "ленинский район", "в ленинском районе",
    "приокский район", "в приокском районе",
    "советский район", "в советском районе",

    # --- Крупные города/округа области (безопасные стемы/формы) ---
    "дзержинск", "в дзержинске", "дзержинска",
    "арзамас", "в арзамасе", "арзамаса",
    "саров", "в сарове", "сарова",
    "выкса", "в выксе", "выксе", "выксунский",
    "кстово", "в кстове", "кстовский", "кстовском",
    "павлово", "в павлове", "павловский",
    "павлово-на-оке", "в павлово-на-оке",
    "балахна", "в балахне", "балахнинский", "балахнинском",
    "богородск", "в богородске", "богородский",
    "городец", "в городеце", "городецкий",
    "лысково", "в лыскове", "лысковский",
    "семёнов", "семенов", "в семёнове", "в семенове", "семёновский", "семеновский",
    "княгинино", "в княгинине", "княгининский",
    "кулебаки", "в кулебаках", "кулебакский",
    "навашино", "в навашино", "навашинский",
    "перевоз (город)", "город перевоз", "в городе перевоз",
    "первомайск", "в первомайске", "первомайский (город)",
    "сергач", "в сергаче", "сергачский",
    "урень", "в урене", "уренский",
    "шахунья", "в шахунье", "шахунский",
    "ветлуга", "в ветлуге", "ветлужский",
    "лукоянов", "в лукоянове", "лукояновский",
    "володарск", "в володарске", "володарский",
    "чкаловск", "в чкаловске", "чкаловский",
    # «бор» — только безопасные варианты (во избежание ложных «оборудование/выборы»)
    "г. бор", "город бор", "в бору", "на бору", "бор (нижегородская область)", "бор нижегородской области",
    # «заволжье» — безопасные варианты (слово часто употребляется как геотермин)
    "г. заволжье", "город заволжье", "заволжье (город)", "заволжье нижегородской области",

    # --- Муниципальные районы/округа области (названия + формы «район/в районе») ---
    "ардатовский район", "в ардатовском районе", "ардатово",
    "большеболдинский район", "в большеболдинском районе", "большое болдино",
    "большемурашкинский район", "в большемурашкинском районе", "большое мурашкино",
    "бутурлинский район", "в бутурлинском районе", "бутурлино",
    "вачский район", "в вачском районе", "вача",
    "варнавинский район", "в варнавинском районе", "варнавино",
    "воскресенский район", "в воскресенском районе", "воскресенское (нн)",
    "воротынский район", "в воротынском районе", "воротынец",
    "выксунский район", "в выксунском районе",  # для старых упоминаний
    "гагинский район", "в гагинском районе", "гагино",
    "городецкий район", "в городецком районе",
    "дивеевский район", "в дивеевском районе", "дивеево",
    "княгининский район", "в княгининском районе",
    "ковернинский район", "в ковернинском районе", "ковернино",
    "краснобаковский район", "в краснобаковском районе", "красные баки",
    "кулебакский район", "в кулебакском районе",
    "лукояновский район", "в лукояновском районе",
    "лысковский район", "в лысковском районе",
    "павловский район", "в павловском районе",
    "перевозский район", "в перевозском районе",
    "первомайский район", "в первомайском районе",
    "пильнинский район", "в пильнинском районе", "пильна",
    "починковский район", "в починковском районе", "починки",
    "сеченовский район", "в сеченовском районе", "сеченово",
    "сергачский район", "в сергачском районе",
    "сосновский район", "в сосновском районе", "сосновское (нн)",
    "спасский район", "в спасском районе", "спасское (нн)",
    "тонкинский район", "в тонкинском районе", "тонкино",
    "тоншаевский район", "в тоншаевском районе", "тоншаево",
    "уренский район", "в уренском районе",
    "шаранский район", "в шаранском районе", "шаранга",
    "шатковский район", "в шатковском районе", "шатки",
    "балахнинский район", "в балахнинском районе",
    "богородский район", "в богородском районе",
    "кстовский район", "в кстовском районе",
    "володарский район", "в володарском районе",
    "чкаловский округ", "в чкаловском округе",
    "шахунский округ", "в шахунском округе",
    "навашинский округ", "в навашинском округе",
]

CONSTRUCTION_KEYWORDS = [
    # --- Инфраструктура и городская среда ---
    "строител", "инфраструктур", "дорог", "развязк", "мост", "тоннел",
    "транспорт", "метро", "трамвай", "жкх", "коммунал", "благоустрой",
    "общественное пространство", "парк", "сквер", "набережн", "пешеходн",

    # --- Жильё и развитие территорий (не только недвижимость) ---
    "капремонт", "реновац", "жилой квартал", "жилой комплекс", "многоэтажн",
    "обновление дворов", "комфортная среда", "городская программа",

    # --- Экономика и бизнес ---
    "экономик", "инвестици", "промышлен", "предприяти", "завод", "производств",
    "кластер", "технопарк", "бизнес", "малый бизнес", "предпринимател",

    # --- Технологии и наука ---
    "цифров", "технолог", "инновац", "научн", "исследован", "инжиниринг",
    "it-проект", "стартап", "робот", "квантов", "космос",

    # --- Социальная сфера ---
    "образован", "школ", "лицей", "гимнази", "детсад", "университет", "колледж",
    "медицин", "здравоохран", "больниц", "поликлин", "скорой помощи",
    "социальн", "волонтер", "поддержк", "семь", "молодеж",

    # --- Культура, туризм, спорт ---
    "культур", "театр", "музей", "филармони", "фестиваль", "концерт",
    "историческ наслед", "туризм", "маршрут", "гостиниц", "санатор",
    "спорт", "соревнован", "матч", "стадион", "фок", "дворец спорта",

    # --- Экология и безопасность ---
    "эколог", "природ", "климат", "зеленая зона", "лес", "водоем", "волга",
    "безопасн", "мчс", "пожарн", "правопоряд", "дорожн безопасн",

    # --- Труд и занятость ---
    "трудоустрой", "занятост", "карьер", "ярмарка вакансий", "центр занятости",
]

GLOBAL_KEYWORDS = [
    "глобальн", "миров", "международн", "саммит", "форум", "геополит",
    "оон", "всемирн", "g20", "g7", "брикс", "нато",
    "россия", "европа", "евросоюз", "сша", "китай", "индия", "япония",
    "германи", "франц", "великобритани", "украин", "беларус",
    "вашингтон", "нью-йорк", "лондон", "берлин", "париж", "пекин", "шанхай", "дубай",
    "финанс", "мировой банк", "мвф", "энергетик", "нефть", "газ", "технолог",
    "космос", "спутник", "nasa", "esa", "кибербезопасн",
]

# === Источники ===
# Примечание:
#  - type="rss" — обычный RSS;
#  - type="html" — одна статья по URL;
#  - type="html_list" — страница-лента с карточками; "selectors" все опциональны.
SOURCES = [
    # === ОФИЦИАЛЬНЫЕ (RSS) — остаются как есть ===
    {"name": "Минград НО — пресс-центр",      "type": "rss", "url": "https://mingrad.nobl.ru/presscenter/news/rss/", "enabled": True},
    {"name": "Госстройнадзор НО — пресс-центр","type": "rss", "url": "https://gsn.nobl.ru/presscenter/news/rss/", "enabled": True},
    {"name": "Минтранс НО — пресс-центр",     "type": "rss", "url": "https://mintrans.nobl.ru/presscenter/news/rss/", "enabled": True},
    {"name": "г.о. Бор — пресс-центр",        "type": "rss", "url": "https://bor.nobl.ru/presscenter/news/rss/", "enabled": True},
    {"name": "Арзамас — пресс-центр",         "type": "rss", "url": "https://arzamas.nobl.ru/presscenter/news/rss/", "enabled": True},
    {"name": "Кстовский округ — пресс-центр", "type": "rss", "url": "https://kstovo.nobl.ru/presscenter/news/rss/", "enabled": True},
    {"name": "Павлово — пресс-центр",         "type": "rss", "url": "https://pavlovo.nobl.ru/presscenter/news/rss/", "enabled": True},
    {"name": "Гордума Нижнего Новгорода",     "type": "rss", "url": "https://www.gordumannov.ru/rss", "enabled": True},
    {"name": "ИА «Время Н»",                  "type": "rss", "url": "https://www.vremyan.ru/rss/news.rss", "enabled": True},

    # === HTML-ЛИСТИНГИ (новые) ===
    # Администрация Нижнего Новгорода — раздел «Строительство»
    {"name": "Администрация НН — Строительство", "type": "html_list",
     "url": "https://admnnov.ru/?id=48",
     "enabled": False,
     "selectors": {
        "item": "article, .news-item, .entry, .post, li",
        "link": "a",
        "title": "h1 a, h2 a, h3 a, h2, h3, a",
        "date": "time, .date, .news-date, .posted-on",
        "date_attr": "datetime"
     }},

    # Правительство НО — лента «Все новости»
    {"name": "Правительство НО — Новости", "type": "html_list",
     "url": "https://nobl.ru/news/",
     "enabled": True,
     "selectors": {
        "item": "article, .news__item, .card, li",
        "link": "a",
        "title": "h2 a, h3 a, h2, h3, a",
        "date": "time, .date, .news-date",
        "date_attr": "datetime"
     }},

    # NewsNN — тег «Строительство»
    {"name": "NewsNN — Строительство", "type": "html_list",
     "url": "https://www.newsnn.ru/tags/stroitelstvo",
     "enabled": True,
     "selectors": {
        "item": "article, .card, .news-item, li",
        "link": "a",
        "title": "h2 a, h3 a, h2, h3, a",
        "date": "time, .date",
        "date_attr": "datetime"
     }},

    # Newsroom24 — основная лента
    {"name": "Newsroom24 — Новости", "type": "html_list",
     "url": "https://newsroom24.ru/news/",
     "enabled": True,
     "selectors": {
        "item": "article, .news, .news-item, .card, li",
        "link": "a",
        "title": "h2 a, h3 a, h2, h3, a",
        "date": "time, .date",
        "date_attr": "datetime"
     }},

    # Говорит Нижний — главная/новости
    {"name": "Говорит Нижний — Новости", "type": "html_list",
     "url": "https://govoritnn.ru/",
     "enabled": True,
     "selectors": {
        "item": "article, .post, .entry, .card, .news, li",
        "link": "a",
        "title": "h2 a, h3 a, h2, h3, a",
        "date": "time, .date, .posted-on",
        "date_attr": "datetime"
     }},

    # НТА-Приволжье — главная/новости
    {"name": "НТА-Приволжье — Новости", "type": "html_list",
     "url": "https://www.nta-nn.ru/",
     "enabled": True,
     "selectors": {
        "item": "article, .news-item, .news, .card, li",
        "link": "a",
        "title": "h2 a, h3 a, h2, h3, a",
        "date": "time, .date, .news-date",
        "date_attr": "datetime"
     }},

    # GIPERNN — Журнал/Жилье/Новости
    {"name": "GIPERNN — Жилье/Новости", "type": "html_list",
     "url": "https://www.gipernn.ru/zhurnal/zhile/novosti",
     "enabled": False,
     "trust_level": 1,
     "min_text_length": 350,
     "rubrics_allowed": ["objects"],
     "selectors": {
        "item": "article, .article, .news-item, .card, li",
        "link": "a",
        "title": "h2 a, h3 a, h2, h3, a",
        "date": "time, .date",
        "date_attr": "datetime"
     }},

    # Столица Нижний — медиа-портал
    {"name": "Столица Нижний (STN Media)", "type": "html_list",
     "url": "https://stnmedia.ru/",
     "enabled": False,
     "timeout": (5, 30),
     "selectors": {
        "item": "article, .news-item, .card, li",
        "link": "a",
        "title": "h2 a, h3 a, h2, h3, a",
        "date": "time, .date",
        "date_attr": "datetime"
     }},

    # STN REALTY — LIVE
    {"name": "STN REALTY — LIVE", "type": "html_list",
     "url": "https://stn-realty.ru/live/",
     "enabled": False,
     "trust_level": 1,
     "min_text_length": 350,
     "rubrics_allowed": ["objects"],
     "selectors": {
        "item": "article, .news-item, .card, li",
        "link": "a",
        "title": "h2 a, h3 a, h2, h3, a",
        "date": "time, .date, .posted-on",
        "date_attr": "datetime"
     }},

    # В городе N — новости
    {"name": "В городе N — Новости", "type": "html_list",
     "url": "https://vgoroden.ru/news/",
     "enabled": False,
     "selectors": {
        "item": "article, .news-item, .news, .card, li",
        "link": "a",
        "title": "h2 a, h3 a, h2, h3, a",
        "date": "time, .date",
        "date_attr": "datetime"
     }},

    # NN.RU — Новости
    {"name": "NN.RU — Новости", "type": "html_list",
     "url": "https://www.nn.ru/news/",
     "enabled": True,
     "selectors": {
        "item": "article, .news, .card, li",
        "link": "a",
        "title": "h2 a, h3 a, h2, h3, a",
        "date": "time, .date, .news-date",
        "date_attr": "datetime"
     }},

    # NN.RU — Недвижимость
    {"name": "NN.RU — Недвижимость", "type": "html_list",
     "url": "https://www.nn.ru/realty/",
     "enabled": True,
     "selectors": {
        "item": "article, .news, .card, li",
        "link": "a",
        "title": "h2 a, h3 a, h2, h3, a",
        "date": "time, .date, .news-date",
        "date_attr": "datetime"
     }},

    # Домострой-НН — Новости
    {"name": "Домострой-НН — Новости", "type": "html_list",
     "url": "https://www.domostroynn.ru/novosti",
     "enabled": True,
     "selectors": {
        "item": "article, .news-item, .card, li",
        "link": "a",
        "title": "h2 a, h3 a, h2, h3, a",
        "date": "time, .date",
        "date_attr": "datetime"
     }},

    # --- Дополнительные медиа-источники (RSS) ---
    {"name": "ГТРК Вести НН", "type": "rss",
     "url": "https://vestinn.ru/rss/",
     "enabled": True},
    {"name": "Аргументы и факты — НН", "type": "rss",
     "url": "https://aif-nn.ru/feed/",
     "enabled": True},
    {"name": "ПроГород Нижний Новгород", "type": "rss",
     "url": "https://progorodnn.ru/rss.xml",
     "enabled": True},
]
# Полностью отключаем сайты при TELEGRAM-only
if ONLY_TELEGRAM:
    for s in SOURCES:
        try:
            s["enabled"] = False
        except Exception:
            pass

# Дополняем основными источниками региона
SOURCES.extend(SOURCES_NN)

if ONLY_TELEGRAM:
    # Повторно отключаем источники после расширения списком региона
    for s in SOURCES:
        s["enabled"] = False

# Быстрые индексы по источникам: по имени и домену
SOURCES_BY_NAME: dict[str, dict] = {}
SOURCES_BY_DOMAIN_ALL: dict[str, list[dict]] = {}
for src in SOURCES:
    name = (src.get("name") or "").strip()
    if name:
        SOURCES_BY_NAME[name] = src
    domain = src.get("source_domain")
    if not domain:
        url = src.get("url", "")
        domain = (urlparse(url).hostname or "").lower()
        if domain.startswith("www."):
            domain = domain[4:]
    if domain:
        try:
            domain = domain.encode("idna").decode("ascii")
        except Exception:
            pass
        SOURCES_BY_DOMAIN_ALL.setdefault(domain, []).append(src)

# === Хранилище ===
# (DB_PATH определяется выше и использует CONFIG_DIR по умолчанию)

# === Telegram ===
ON_SEND_ERROR: str = os.getenv("ON_SEND_ERROR", "retry").strip().lower()
PUBLISH_MAX_RETRIES: int = int(os.getenv("PUBLISH_MAX_RETRIES", "2"))
RETRY_BACKOFF_SECONDS: float = float(os.getenv("RETRY_BACKOFF_SECONDS", "2.5"))
PUBLISH_SLEEP_BETWEEN_SEC: float = float(os.getenv("PUBLISH_SLEEP_BETWEEN_SEC", "0"))

# === Рерайт (опц.) ===
REWRITE_MAX_CHARS = int(os.getenv("REWRITE_MAX_CHARS", "600"))

# === Кластеризация похожих заголовков (опц.) ===
ENABLE_TITLE_CLUSTERING = os.getenv("ENABLE_TITLE_CLUSTERING", "false").lower() in {"1", "true", "yes"}
CLUSTER_SIM_THRESHOLD = float(os.getenv("CLUSTER_SIM_THRESHOLD", "0.85"))
CLUSTER_LOOKBACK_DAYS = int(os.getenv("CLUSTER_LOOKBACK_DAYS", "14"))
CLUSTER_MAX_CANDIDATES = int(os.getenv("CLUSTER_MAX_CANDIDATES", "200"))

# === Опрос источников ===
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "600"))
FETCH_LIMIT_PER_SOURCE = int(os.getenv("FETCH_LIMIT_PER_SOURCE", "30"))
FETCH_DAYS_BACK = int(os.getenv("FETCH_DAYS_BACK", "7"))
BATCH_SIMILARITY_THRESHOLD = float(
    os.getenv("BATCH_SIMILARITY_THRESHOLD", str(CLUSTER_SIM_THRESHOLD))
)


def init_config_file(path: Path = ENV_PATH) -> None:
    """Interactive helper to create the persistent .env file."""
    if path.exists():
        print(f"Configuration already exists at {path}")
        return

    token = input("Enter BOT_TOKEN: ").strip()
    channel = input("Enter CHANNEL_ID: ").strip()
    admin = input("Enter ADMIN_CHAT_ID (optional): ").strip()

    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"BOT_TOKEN={token}\n")
        fh.write(f"CHANNEL_ID={channel}\n")
        if admin:
            fh.write(f"ADMIN_CHAT_ID={admin}\n")

    print(f"Configuration written to {path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Manage NewsBot configuration")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init", help="create persistent configuration")
    args = parser.parse_args()

    if args.command == "init":
        init_config_file()
    else:
        parser.print_help()

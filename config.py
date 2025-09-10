import os
from pathlib import Path

from dotenv import load_dotenv
from platformdirs import user_config_dir

try:  # pragma: no cover - список источников региона
    from sources_nn import SOURCES_NN
except Exception:  # pragma: no cover - файл может отсутствовать
    SOURCES_NN: list[dict] = []


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
        FALLBACK_IMAGE_URL as DEFAULT_FALLBACK_IMAGE_URL,
    )
except Exception:  # pragma: no cover - executed only when defaults missing
    DEFAULT_BOT_TOKEN = ""
    DEFAULT_CHANNEL_ID = ""
    DEFAULT_ENABLE_MODERATION = False
    DEFAULT_REVIEW_CHAT_ID = ""
    DEFAULT_MODERATOR_IDS: set[int] = set()
    DEFAULT_FALLBACK_IMAGE_URL = "https://example.com/placeholder.png"

# === Базовые настройки бота ===
# Support both legacy names and new explicit TELEGRAM_* variables
BOT_TOKEN: str = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("BOT_TOKEN", DEFAULT_BOT_TOKEN)
).strip()
CHANNEL_ID: str = os.getenv("CHANNEL_ID", DEFAULT_CHANNEL_ID).strip()  # пример: "@my_news_channel" или числовой ID
RETRY_LIMIT: int = int(os.getenv("RETRY_LIMIT", "3"))

# === HTTP-клиент ===
HTTP_TIMEOUT_CONNECT: float = float(os.getenv("HTTP_TIMEOUT_CONNECT", "5"))
# ТЗ: смягчённые таймауты (connect=5s, read=10s)
HTTP_TIMEOUT_READ: float = float(os.getenv("HTTP_TIMEOUT_READ", "10"))
HTTP_RETRY_TOTAL: int = int(os.getenv("HTTP_RETRY_TOTAL", "3"))
HTTP_BACKOFF: float = float(os.getenv("HTTP_BACKOFF", "0.5"))

# === Флаги и режимы ===
ENABLE_REWRITE: bool = os.getenv("ENABLE_REWRITE", "true").lower() in {"1", "true", "yes"}
STRICT_FILTER: bool = os.getenv("STRICT_FILTER", "1").lower() in {"1", "true", "yes"}
ENABLE_MODERATION: bool = os.getenv("ENABLE_MODERATION", str(DEFAULT_ENABLE_MODERATION)).lower() in {"1", "true", "yes"}
ADMIN_CHAT_ID: str = os.getenv("ADMIN_CHAT_ID", "").strip()
ALLOW_IMAGES: bool = os.getenv("ALLOW_IMAGES", "true").lower() in {"1", "true", "yes"}  # разрешить обработку изображений
MIN_IMAGE_BYTES: int = int(os.getenv("MIN_IMAGE_BYTES", "4096"))  # минимальный размер файла изображения
IMAGE_TIMEOUT: int = int(os.getenv("IMAGE_TIMEOUT", "15"))  # таймаут загрузки изображений (сек)
IMAGE_ALLOWED_DOMAINS = set(
    s.strip().lower()
    for s in os.getenv("IMAGE_ALLOWED_DOMAINS", "").split(",")
    if s.strip()
)
IMAGE_MIN_RATIO: float = float(os.getenv("IMAGE_MIN_RATIO", "0.5"))
IMAGE_MAX_RATIO: float = float(os.getenv("IMAGE_MAX_RATIO", "3.0"))
IMAGE_ALLOWED_EXT = set(
    e.strip().lower()
    for e in os.getenv("IMAGE_ALLOWED_EXT", ".jpg,.jpeg,.png,.webp").split(",")
    if e.strip()
)
IMAGE_DENYLIST_DOMAINS = set(
    d.strip().lower()
    for d in os.getenv("IMAGE_DENYLIST_DOMAINS", "mc.yandex.ru,top-fwz1.mail.ru,counter,logo,pixel").split(",")
    if d.strip()
)

# --- New image subsystem flags ---
CONTEXT_IMAGE_ENABLED: bool = os.getenv("CONTEXT_IMAGE_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
}
CONTEXT_IMAGE_PREFERRED: bool = os.getenv(
    "CONTEXT_IMAGE_PREFERRED", "false"
).lower() in {"1", "true", "yes"}
CONTEXT_IMAGE_PROVIDERS: str = os.getenv(
    "CONTEXT_IMAGE_PROVIDERS", "openverse,wikimedia"
)
CONTEXT_LICENSES: str = os.getenv(
    "CONTEXT_LICENSES", "cc0,cc-by,cc-by-sa"
)
ALLOW_PLACEHOLDER: bool = os.getenv("ALLOW_PLACEHOLDER", "false").lower() in {
    "1",
    "true",
    "yes",
}
MAX_IMAGE_BYTES: int = int(os.getenv("MAX_IMAGE_BYTES", "18874368"))
IMAGES_CACHE_DIR: str = os.getenv("IMAGES_CACHE_DIR", "./cache/images")
REGION_HINT: str = os.getenv("REGION_HINT", "Нижегородская область")

FALLBACK_IMAGE_URL: str = os.getenv(
    "FALLBACK_IMAGE_URL",
    DEFAULT_FALLBACK_IMAGE_URL,
).strip()

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

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
ATTACH_IMAGES: bool = os.getenv("ATTACH_IMAGES", "true").lower() in {"1", "true", "yes"}
ENABLE_IMAGE_PIPELINE: bool = os.getenv("ENABLE_IMAGE_PIPELINE", "false").lower() in {"1", "true", "yes"}
MAX_MEDIA_PER_POST: int = int(os.getenv("MAX_MEDIA_PER_POST", "10"))
IMAGE_MIN_EDGE: int = int(os.getenv("IMAGE_MIN_EDGE", "220"))
IMAGE_MIN_AREA: int = int(os.getenv("IMAGE_MIN_AREA", "45000"))
SNOOZE_MINUTES: int = int(os.getenv("SNOOZE_MINUTES", "0"))
REVIEW_TTL_HOURS: int = int(os.getenv("REVIEW_TTL_HOURS", "24"))
CAPTION_LIMIT: int = int(os.getenv("CAPTION_LIMIT", "1024"))
TELEGRAM_MESSAGE_LIMIT: int = int(os.getenv("TELEGRAM_MESSAGE_LIMIT", "4096"))
PREVIEW_MODE: str = os.getenv("PREVIEW_MODE", "auto")
_RAW_PARSE_MODE = os.getenv("PARSE_MODE", os.getenv("TELEGRAM_PARSE_MODE", "HTML"))
if _RAW_PARSE_MODE.strip().lower() == "markdownv2":
    TELEGRAM_PARSE_MODE: str = "MarkdownV2"
elif _RAW_PARSE_MODE.strip().lower() == "html":
    TELEGRAM_PARSE_MODE = "HTML"
else:
    TELEGRAM_PARSE_MODE = _RAW_PARSE_MODE.strip()
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

# --- Database ---
DB_PATH: str = os.getenv("DB_PATH", str(CONFIG_DIR / "newsbot.db")).strip()


def validate_config() -> None:
    """Validate critical configuration values with clear errors."""

    missing: list[str] = []
    if BOT_TOKEN in {"", "YOUR_TELEGRAM_BOT_TOKEN"}:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not str(CHANNEL_CHAT_ID) and not CHANNEL_ID:
        missing.append("CHANNEL_CHAT_ID or CHANNEL_ID")
    if ENABLE_MODERATION:
        if str(REVIEW_CHAT_ID) in {"", "@your_review_channel"}:
            missing.append("REVIEW_CHAT_ID")
        if not MODERATOR_IDS:
            missing.append("MODERATOR_IDS")
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
    # --- Базовые стемы по стройке/СМР/вводу ---
    "строител",                 # строить, строительство, строительные, строительный
    "стройработ",               # стройработы
    "смр",                      # строительно-монтажные работы
    "строительно-монтажн",
    "возведен", "возведут", "возводят", "возведение",
    "построят", "построен", "построили", "построить",
    "ввод в эксплуатац", "ввели в эксплуатац", "ввод объекта", "ввести в эксплуатац",
    "разрешение на стро", "разрешение на ввод",
    "госкомисси", "приемка объекта", "акт ввода",

    # --- Реконструкция/капремонт/снос/благоустройство ---
    "реконструкц",              # реконструкция, реконструируют, реконструирован
    "капремонт", "капитальный ремонт",
    "снос", "демонтаж",
    "благоустройст", "благоустро", "реновац", "крт",  # комплексное развитие территорий

    # --- Девелопмент/застройщик/подряд ---
    "девелопер", "девелопмент",
    "застройщик", "застройк",   # застройка территории
    "генподряд", "подрядчик", "подрядн", "субподряд",
    "техзаказчик", "заказчик строительства",
    "проектная документац", "экспертиза проектной документац", "госэкспертиз",

    # --- Жильё/объекты недвижимости (аккуратно, без короткого «жк») ---
    "жилой комплекс", "многоквартирн", "многоэтажн", "домостроен",
    "инфраструктурный объект", "объект строительства", "объект капитального строительства", "окск",

    # --- Инженерные сети и объекты ---
    "инженерн сет", "инженерн инфраструктур",
    "водопровод", "канализац", "ливнев", "водоотведен",
    "теплосет", "котельн", "теплоисточн", "теплотрасс",
    "газопровод", "грп", "грсу",
    "лэп", "подстанц", "электросет", "кабельн лини",
    "очистные сооружен", "кнс", "нвк", "водозаборн сооружен", "насосн станц", "резервуар чистой воды",

    # --- Транспорт/дороги/мосты/метро ---
    "дорожные работы", "дорожн работ",
    "ремонт дороги", "капитальный ремонт дороги", "реконструкция дороги",
    "транспортная развязк", "развязк", "эстакад", "путепровод", "тоннел",
    "мост", "ремонт моста", "строительство моста",
    "трамвайная лини", "трамвайное полотно", "контактн сеть",
    "метро", "станция метро", "электродепо",

    # --- Соцобъекты (только с явным строительным контекстом) ---
    "строительство школы", "строительство детского сада",
    "строительство поликлиники", "строительство больницы",
    "строительство фока", "строительство спорткомплекса",
    "строительство стадиона", "строительство дворца спорта",
    "строительство ледового", "строительство бассейна",

    # --- Урбанистика/градрегламенты/планировка ---
    "генплан", "градплан", "градостроительн план", "гпзу",
    "проект планировки территор", "ппт",
    "правила землепользования и застройки", "пзз",
    "межеван", "редевелопмент", "реорганизац территор",

    # --- Программы и формулировки из пресс-релизов ---
    "нацпроект", "федеральная программ", "региональная программ",
    "комплексное освоение территор", "общественно-деловая застройк",
    "инвестиционный проект", "инфраструктурный проект", "гчп", "концесс",
]

# === Источники ===
# Примечание:
#  - type="rss" — обычный RSS;
#  - type="html" — одна статья по URL;
#  - type="html_list" — страница-лента с карточками; "selectors" все опциональны.
SOURCES = [
    # === ОФИЦИАЛЬНЫЕ (RSS) — остаются как есть ===
    {"name": "Минград НО — пресс-центр",      "type": "rss", "url": "https://mingrad.nobl.ru/presscenter/news/rss/", "enabled": True},
    {"name": "Госстройнадзор НО — пресс-центр","type": "rss", "url": "https://nngosnadzor.nobl.ru/presscenter/news/rss/", "enabled": True},
    {"name": "Минтранс НО — пресс-центр",     "type": "rss", "url": "https://mintrans.nobl.ru/presscenter/news/rss/", "enabled": True},
    {"name": "г.о. Бор — пресс-центр",        "type": "rss", "url": "https://bor.nobl.ru/presscenter/news/rss/", "enabled": True},
    {"name": "Арзамас — пресс-центр",         "type": "rss", "url": "https://arzamas.nobl.ru/presscenter/news/rss/", "enabled": True},
    {"name": "Кстовский округ — пресс-центр", "type": "rss", "url": "https://kstovo.nobl.ru/presscenter/news/rss/", "enabled": True},
    {"name": "Павлово — пресс-центр",         "type": "rss", "url": "https://pavlovo.nobl.ru/presscenter/news/rss/", "enabled": True},
    {"name": "Гордума Нижнего Новгорода",     "type": "rss", "url": "https://www.duma.nnov.ru/rss", "enabled": True},
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
     "enabled": True,
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
     "enabled": True,
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
     "enabled": True,
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

# Дополняем основными источниками региона
SOURCES.extend(SOURCES_NN)

# === Хранилище ===
DB_PATH: str = os.getenv("DB_PATH", "newsbot.db")

# === Telegram ===
PARSE_MODE: str = os.getenv("PARSE_MODE", os.getenv("TELEGRAM_PARSE_MODE", "HTML")).strip()
TELEGRAM_PARSE_MODE: str = PARSE_MODE
TELEGRAM_DISABLE_WEB_PAGE_PREVIEW: bool = os.getenv("TELEGRAM_DISABLE_WEB_PAGE_PREVIEW", "true").lower() in {"1", "true", "yes"}
TELEGRAM_MESSAGE_LIMIT: int = int(os.getenv("TELEGRAM_MESSAGE_LIMIT", "4096"))
ON_SEND_ERROR: str = os.getenv("ON_SEND_ERROR", "retry").strip().lower()
PUBLISH_MAX_RETRIES: int = int(os.getenv("PUBLISH_MAX_RETRIES", "2"))
RETRY_BACKOFF_SECONDS: float = float(os.getenv("RETRY_BACKOFF_SECONDS", "2.5"))
PUBLISH_SLEEP_BETWEEN_SEC: float = float(os.getenv("PUBLISH_SLEEP_BETWEEN_SEC", "0"))

# === Рерайт (опц.) ===
REWRITE_MAX_CHARS = int(os.getenv("REWRITE_MAX_CHARS", "600"))
EXTERNAL_AI_ENABLED = os.getenv("EXTERNAL_AI_ENABLED", "false").lower() in {"1", "true", "yes"}
EXTERNAL_AI_ENDPOINT = os.getenv("EXTERNAL_AI_ENDPOINT", "")
EXTERNAL_AI_KEY = os.getenv("EXTERNAL_AI_KEY", "")

# === Кластеризация похожих заголовков (опц.) ===
ENABLE_TITLE_CLUSTERING = os.getenv("ENABLE_TITLE_CLUSTERING", "false").lower() in {"1", "true", "yes"}
CLUSTER_SIM_THRESHOLD = float(os.getenv("CLUSTER_SIM_THRESHOLD", "0.8"))
CLUSTER_LOOKBACK_DAYS = int(os.getenv("CLUSTER_LOOKBACK_DAYS", "14"))
CLUSTER_CANDIDATES = int(os.getenv("CLUSTER_CANDIDATES", "200"))

# === Опрос источников ===
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "600"))
FETCH_LIMIT_PER_SOURCE = int(os.getenv("FETCH_LIMIT_PER_SOURCE", "30"))


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

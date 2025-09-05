"""Configuration for newsbot.

Contains keywords for filtering and a list of news sources.
"""

# Keywords for filtering news items
REGION_KEYWORDS = [
    "нижегородская область",
]

CONSTRUCTION_KEYWORDS = [
    "строительство",
]

# Combined list used by the bot for filtering
KEYWORDS = REGION_KEYWORDS + CONSTRUCTION_KEYWORDS

# RSS or HTML sources to poll for news
SOURCES = [
    {
        "name": "NN.ru",
        "type": "rss",
        "url": "https://www.nn.ru/news/rss",
        "selectors": {},
    },
    {
        "name": "Vremyan.ru",
        "type": "rss",
        "url": "https://www.vremyan.ru/rss",
        "selectors": {},
    },
    {
        "name": "StroyPortal",
        "type": "rss",
        "url": "https://stroyportal.ru/news/rss",
        "selectors": {},
    },
]

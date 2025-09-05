"""Configuration for newsbot.

Contains keyword lists for filtering and a list of news sources.
"""

# Regional keywords for filtering news items
REGION_KEYWORDS = [
    "нижегородская область",
]

# Construction keywords for filtering news items
CONSTRUCTION_KEYWORDS = [
    "строительство",
]

# Combined list for backward compatibility
KEYWORDS = REGION_KEYWORDS + CONSTRUCTION_KEYWORDS

# News sources to poll. Each source is a dict with ``type`` and ``url`` keys.
# ``type`` may be ``rss``, ``html_list`` or ``html``. Optional CSS selectors
# can be provided via the ``selectors`` dictionary.
SOURCES = [
    {"type": "rss", "url": "https://hnrss.org/frontpage"},
    {"type": "html_list", "url": "https://example.com", "selectors": {"items": "a"}},
    {"type": "html", "url": "https://httpbin.org/html", "selectors": {"title": "h1", "link": "a"}},
]

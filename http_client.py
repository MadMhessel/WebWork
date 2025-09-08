import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config

_session = None


def get_session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.trust_env = False
        s.headers.update({"User-Agent": "newsbot/1.0"})
        retries = Retry(
            total=config.HTTP_RETRY_TOTAL,
            backoff_factor=config.HTTP_BACKOFF,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
        )
        adapter = HTTPAdapter(max_retries=retries)
        s.mount("http://", adapter)
        s.mount("https://", adapter)
        _session = s
    return _session

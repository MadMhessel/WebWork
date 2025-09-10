import logging
import os
import time
from urllib.parse import urlparse
from typing import Optional, Dict

import requests

try:  # pragma: no cover
    from . import config, http_client
except Exception:  # pragma: no cover
    import config  # type: ignore
    import http_client  # type: ignore

logger = logging.getLogger(__name__)

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "ru,en;q=0.9",
}


def _timeout(read: Optional[float]) -> tuple[float, float]:
    connect = getattr(config, "HTTP_TIMEOUT_CONNECT", 5.0)
    read_default = getattr(config, "HTTP_TIMEOUT_READ", 10.0)
    read_to = max(read_default, read or 0.0)
    return (connect, read_to)


def _need_verify(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    disabled = getattr(config, "SSL_NO_VERIFY_HOSTS", set())
    return host not in disabled


def _request(
    url: str,
    *,
    timeout: Optional[float] = None,
    allow_redirects: bool = True,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, str]] = None,
    stream: bool = False,
) -> requests.Response:
    sess = http_client.get_session()
    hdrs = dict(_BROWSER_HEADERS)
    if headers:
        hdrs.update(headers)
    verify = _need_verify(url)
    t = _timeout(timeout)
    total = int(getattr(config, "HTTP_RETRY_TOTAL", 3))
    backoff = float(getattr(config, "HTTP_BACKOFF", 0.5))
    last_exc: Optional[Exception] = None
    for attempt in range(total):
        try:
            resp = sess.get(
                url,
                timeout=t,
                allow_redirects=allow_redirects,
                headers=hdrs,
                verify=verify,
                params=params,
                stream=stream,
            )
            if resp.status_code >= 500:
                raise requests.HTTPError(f"{resp.status_code} server error")
            return resp
        except requests.RequestException as ex:  # pragma: no cover - network
            last_exc = ex
            if attempt < total - 1:
                time.sleep(backoff * (2 ** attempt))
                continue
            raise
    raise last_exc  # type: ignore[misc]


def get_text(
    url: str,
    *,
    timeout: Optional[float] = None,
    allow_redirects: bool = True,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, str]] = None,
) -> str:
    resp = _request(
        url,
        timeout=timeout,
        allow_redirects=allow_redirects,
        headers=headers,
        params=params,
    )
    try:
        resp.raise_for_status()
        return resp.text
    finally:
        resp.close()


def get_bytes(
    url: str,
    *,
    timeout: Optional[float] = None,
    allow_redirects: bool = True,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, str]] = None,
) -> bytes:
    resp = _request(
        url,
        timeout=timeout,
        allow_redirects=allow_redirects,
        headers=headers,
        params=params,
        stream=True,
    )
    try:
        resp.raise_for_status()
        return resp.content
    finally:
        resp.close()


_PIXEL_PATTERNS = ["vk.com/rtrg", "metrika", "pixel", "counter", "stats"]


def is_downloadable_image_url(u: str) -> bool:
    if not u:
        return False
    u = u.strip()
    parsed = urlparse(u)
    if parsed.scheme not in {"http", "https"}:
        return False
    low = u.lower()
    if any(p in low for p in _PIXEL_PATTERNS):
        return False
    _, ext = os.path.splitext(parsed.path)
    if ext.lower() in {".svg", ".gif"}:
        return False
    return True

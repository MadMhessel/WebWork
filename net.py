# import-shim: allow running as a script (no package parent)
if __name__ == "__main__" or __package__ is None:
    import os
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
# end of shim

import time
from urllib.parse import urlparse
from typing import Optional, Dict

import requests

import config
import http_client

from logging_setup import get_logger

logger = get_logger(__name__)

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


def _verify_for(url: str) -> bool:
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
    verify: Optional[bool] = None,
) -> requests.Response:
    sess = http_client.get_session()
    hdrs = dict(_BROWSER_HEADERS)
    if headers:
        hdrs.update(headers)
    verify_flag = _verify_for(url) if verify is None else verify
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
                verify=verify_flag,
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
    verify: Optional[bool] = None,
) -> str:
    resp = _request(
        url,
        timeout=timeout,
        allow_redirects=allow_redirects,
        headers=headers,
        params=params,
        verify=verify,
    )
    try:
        resp.raise_for_status()
        return resp.text
    finally:
        resp.close()


def get_text_with_meta(
    url: str,
    *,
    timeout: Optional[float] = None,
    allow_redirects: bool = True,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, str]] = None,
    verify: Optional[bool] = None,
) -> tuple[str, Dict[str, str], int]:
    resp = _request(
        url,
        timeout=timeout,
        allow_redirects=allow_redirects,
        headers=headers,
        params=params,
        verify=verify,
    )
    try:
        status = resp.status_code
        headers_out = dict(resp.headers or {})
        if status == 304:
            return "", headers_out, status
        resp.raise_for_status()
        return resp.text, headers_out, status
    finally:
        resp.close()


def get_bytes(
    url: str,
    *,
    timeout: Optional[float] = None,
    allow_redirects: bool = True,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, str]] = None,
    verify: Optional[bool] = None,
) -> bytes:
    resp = _request(
        url,
        timeout=timeout,
        allow_redirects=allow_redirects,
        headers=headers,
        params=params,
        stream=True,
        verify=verify,
    )
    try:
        resp.raise_for_status()
        return resp.content
    finally:
        resp.close()



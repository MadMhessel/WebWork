"""HTTP client factory with retries, timeouts and logging."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Optional

import requests
from requests import Response, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import http_cfg

logger = logging.getLogger(__name__)


@lru_cache()
def session() -> Session:
    cfg = http_cfg()
    sess = requests.Session()
    sess.trust_env = False
    retry = Retry(
        total=cfg.retry_total,
        backoff_factor=cfg.backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD", "OPTIONS", "TRACE"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    sess.mount("http://", adapter)
    sess.mount("https://", adapter)
    return sess


def request(
    method: str,
    url: str,
    *,
    timeout: Optional[float] = None,
    context: Optional[str] = None,
    **kwargs: Any,
) -> Response:
    """Perform an HTTP request with centralised error handling."""

    cfg = http_cfg()
    sess = session()
    effective_timeout = timeout if timeout is not None else cfg.timeout
    try:
        response = sess.request(method.upper(), url, timeout=effective_timeout, **kwargs)
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        if context:
            logger.warning("HTTP %s %s failed (%s): %s", method, url, context, exc)
        else:
            logger.warning("HTTP %s %s failed: %s", method, url, exc)
        raise

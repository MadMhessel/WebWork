from typing import Any, Optional

import requests

from webwork.http_client import request as _request
from webwork.http_client import session as _session


def get_session() -> requests.Session:
    """Return a shared HTTP session configured with retries and timeouts."""

    return _session()


def request(
    method: str,
    url: str,
    *,
    timeout: Optional[float] = None,
    context: Optional[str] = None,
    **kwargs: Any,
) -> requests.Response:
    """Proxy to the shared request helper that logs failures."""

    return _request(method, url, timeout=timeout, context=context, **kwargs)

from __future__ import annotations

import requests
from typing import Optional


class FetchError(Exception):
    pass


def fetch_head(url: str, *, timeout: float = 5.0) -> requests.Response:
    resp = requests.head(url, timeout=timeout, allow_redirects=True)
    if resp.status_code >= 400:
        raise FetchError(f"status {resp.status_code}")
    return resp


def fetch_get(url: str, *, timeout: float = 5.0) -> bytes:
    resp = requests.get(url, timeout=timeout)
    if resp.status_code >= 400:
        raise FetchError(f"status {resp.status_code}")
    return resp.content

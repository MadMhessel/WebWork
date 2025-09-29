import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from teleapi_client import normalize_telegram_link


def test_normalize_plain_alias() -> None:
    assert normalize_telegram_link("@example") == "example"


def test_normalize_http_alias() -> None:
    assert normalize_telegram_link("https://t.me/s/news_feed") == "news_feed"


def test_normalize_without_prefix() -> None:
    assert normalize_telegram_link("channel42") == "channel42"


def test_normalize_trims_whitespace() -> None:
    assert normalize_telegram_link("  https://t.me/channel  ") == "channel"


def test_normalize_invalid_returns_none() -> None:
    assert normalize_telegram_link("") is None
    assert normalize_telegram_link("not a link") is None

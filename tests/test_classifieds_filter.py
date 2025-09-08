import pathlib
import sys

# add repo parent to sys.path
sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))

from WebWork import classifieds


def test_blocked_domain_detects_classified():
    title = "Продам квартиру"
    content = "Цена 5 млн руб. Звонить +7 123 456-78-90"
    url = "https://avito.ru/nn/prodam-kvartiru-123"
    assert classifieds.is_classified(title, content, url) is True


def test_whitelist_allows_news():
    title = "Обзор рынка недвижимости"
    content = ""
    url = "https://example.com/news/market"
    assert classifieds.is_classified(title, content, url) is False


def test_combined_scoring_without_blocked_domain():
    title = "Сдаю офис"
    content = "50 тыс. руб в мес. Тел. +7 111 222-33-44"
    url = "https://example.com/arenda-ofisa"
    assert classifieds.is_classified(title, content, url) is True

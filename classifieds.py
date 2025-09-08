# -*- coding: utf-8 -*-
import re
from dataclasses import dataclass, field
from typing import Dict, List
from urllib.parse import urlparse


@dataclass
class ClassifiedsConfig:
    threshold: int = 5
    blocked_domains: List[str] = field(default_factory=lambda: [
        "avito.ru", "cian.ru", "realty.yandex.ru", "domofond.ru", "irr.ru",
        "youla.ru", "domclick.ru", "move.ru", "kvadroom.ru", "mlsn.ru",
        "restate.ru", "gidkvartir.ru", "n1.ru", "bn.ru", "sob.ru",
        "realty.rbc.ru", "tzan.ru", "realty.mail.ru", "realty.rambler.ru",
        "etagirealty.ru", "kvadrealty.ru", "yavito.ru", "kvadrometr.ru"
    ])
    url_slug_patterns: List[str] = field(default_factory=lambda: [
        r"/kupit[-_/]", r"/prodazha[-_/]", r"/prodaja[-_/]", r"/snyat[-_/]",
        r"/sdat[-_/]", r"/arenda[-_/]", r"/kommercheskaya[-_/]nedvizhimost",
        r"/ofisy[-_/]", r"/sklady[-_/]", r"/torgovye[-_/]ploshchadi",
        r"/magaziny[-_/]", r"/kvartiry[-_/]", r"/komnaty[-_/]"
    ])
    title_core_patterns: List[str] = field(default_factory=lambda: [
        r"\b(продажа|прода[её]тся|продам|продамся|продаю|купить|куплю|сдать|сда[её]тся|сдам|сдамся|сдаю|аренда|арендую|арендная ставка|в аренду)\b",
        r"\b(объявлени\w*|предложени\w*|прайс\w*|каталог\w*|выгодн\w+ цен\w+|лучш\w+ цен\w+)\b",
        r"\b(сниму|ищу жиль\w+|поиск\w+ жиль\w+)\b",
        r"\b(офис\w*|склад\w*|торгов\w+ площад\w+|коммерческ\w+ недвижим\w+|нежил\w+ помещен\w+)\b",
        r"\b(квартир\w*|комнат\w*|дом\w*|коттедж\w*|таунхаус\w*|апартамен\w*)\b"
    ])
    listing_count_patterns: List[str] = field(default_factory=lambda: [
        r"(?:—|-|—)\s*\d+\s+объявлен\w+",
        r"\b\d+\s+объявлен\w+\b",
        r"\b\d+\s+предложени\w+\b"
    ])
    price_patterns: List[str] = field(default_factory=lambda: [
        r"\b\d[\d\s]{0,3}\d(?:[\s\u00A0]?\d{3})*(?:[.,]\d{1,2})?\s?(?:₽|руб\.?|рублей)\b",
        r"\b(тыс\.|млн|млрд)\s?(?:₽|руб\.?|рублей)\b",
        r"\bза\s?м[²2]\b",
        r"\bв\s?мес(?:яц)?\b"
    ])
    contact_patterns: List[str] = field(default_factory=lambda: [
        r"(?:\+7|8)\s?\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}",
        r"\bтел\.?\b", r"\bwhats?app\b", r"\bтелеграм\b",
        r"\bзвонить\b", r"\bнаписать\b"
    ])
    lot_id_patterns: List[str] = field(default_factory=lambda: [
        r"\b(ID|Id|id|лот|№)\s?[#:]?\s?\d{3,}\b"
    ])
    cta_patterns: List[str] = field(default_factory=lambda: [
        r"\b(перейти|смотреть|показать|развернуть|покажем|оставить заявку|добавить объявление)\b"
    ])
    whitelist_title_patterns: List[str] = field(default_factory=lambda: [
        r"\b(рынок|аналитика|обзор|итоги|исследовани\w+|статистик\w+)\b",
        r"\b(закон|законопроект|постановлени\w+|регулат\w+)\b",
        r"\b(строит\w+|ввод\w+ в эксплуатаци\w+|сдан\w+ объект\w+)\b"
    ])
    weights: Dict[str, int] = field(default_factory=lambda: {
        "blocked_domain": 6,
        "url_slug": 4,
        "title_core": 3,
        "listing_count": 5,
        "price": 3,
        "contact": 4,
        "lot_id": 3,
        "cta": 2,
    })


class ClassifiedsFilter:
    def __init__(self, cfg: ClassifiedsConfig | None = None):
        self.cfg = cfg or ClassifiedsConfig()
        self._compile()

    def _compile(self) -> None:
        self._url_slug = [re.compile(p, re.I) for p in self.cfg.url_slug_patterns]
        self._title_core = [re.compile(p, re.I) for p in self.cfg.title_core_patterns]
        self._listing_count = [re.compile(p, re.I) for p in self.cfg.listing_count_patterns]
        self._price = [re.compile(p, re.I) for p in self.cfg.price_patterns]
        self._contact = [re.compile(p, re.I) for p in self.cfg.contact_patterns]
        self._lot_id = [re.compile(p, re.I) for p in self.cfg.lot_id_patterns]
        self._cta = [re.compile(p, re.I) for p in self.cfg.cta_patterns]
        self._whitelist_title = [re.compile(p, re.I) for p in self.cfg.whitelist_title_patterns]

    @staticmethod
    def _matches(text: str, patterns: List[re.Pattern]) -> bool:
        return any(p.search(text) for p in patterns)

    def score(self, title: str, content: str, url: str) -> int:
        title = (title or "").lower()
        content = (content or "").lower()
        url = (url or "").lower()

        if self._matches(title, self._whitelist_title):
            return 0

        score = 0
        domain = urlparse(url).hostname or ""
        domain = domain.lower()
        for d in self.cfg.blocked_domains:
            if domain == d or domain.endswith("." + d):
                score += self.cfg.weights.get("blocked_domain", 0)
                break

        if self._matches(url, self._url_slug):
            score += self.cfg.weights.get("url_slug", 0)

        text = f"{title}\n{content}"
        if self._matches(text, self._title_core):
            score += self.cfg.weights.get("title_core", 0)
        if self._matches(text, self._listing_count):
            score += self.cfg.weights.get("listing_count", 0)
        if self._matches(text, self._price):
            score += self.cfg.weights.get("price", 0)
        if self._matches(text, self._contact):
            score += self.cfg.weights.get("contact", 0)
        if self._matches(text, self._lot_id):
            score += self.cfg.weights.get("lot_id", 0)
        if self._matches(text, self._cta):
            score += self.cfg.weights.get("cta", 0)
        return score

    def is_classified(self, title: str, content: str, url: str) -> bool:
        return self.score(title, content, url) >= self.cfg.threshold


_default_filter = ClassifiedsFilter()


def is_classified(title: str, content: str, url: str, flt: ClassifiedsFilter | None = None) -> bool:
    return (flt or _default_filter).is_classified(title, content, url)


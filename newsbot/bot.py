"""Minimal bot logic for newsbot.

These functions are placeholders demonstrating how the CLI might
interact with the rest of the system.
"""

import time
from typing import Iterable, Dict
from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup

from .config import KEYWORDS, SOURCES


def fetch_from_sources(use_mock: bool = False, limit: int = 10) -> Iterable[Dict[str, str]]:
    """Fetch and yield items from configured sources.

    Uses ``requests`` to retrieve content from each URL in ``SOURCES`` and
    attempts to parse it as RSS/Atom using ``feedparser``. If no feed entries
    are found, it falls back to basic HTML parsing with ``BeautifulSoup``.

    Each yielded item contains ``title``, ``url`` and ``guid`` keys. Network
    errors are caught and reported to avoid crashing the bot.

    Parameters
    ----------
    use_mock: bool
        When True, mock items are yielded without performing network requests.
    limit: int
        Maximum number of items to yield per source.
    """

    for src in SOURCES:
        if use_mock:
            yield {
                "title": f"Нижегородская область строительство news from {src}",
                "url": src,
                "guid": src,
            }
            continue

        try:
            response = requests.get(src, timeout=10)
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"Error fetching {src}: {exc}")
            continue

        feed = feedparser.parse(response.content)
        entries = getattr(feed, "entries", [])

        if entries:
            for entry in entries[:limit]:
                title = entry.get("title", "").strip()
                link = entry.get("link", src).strip()
                guid = entry.get("id") or entry.get("guid") or link
                yield {"title": title, "url": link, "guid": guid}
            continue

        soup = BeautifulSoup(response.text, "html.parser")
        links = soup.find_all("a", href=True)
        for tag in links[:limit]:
            title = tag.get_text(strip=True)
            if not title:
                continue
            link = urljoin(src, tag["href"])
            yield {"title": title, "url": link, "guid": link}


def filter_items(items: Iterable[Dict[str, str]]) -> Iterable[Dict[str, str]]:
    """Filter items that contain all keywords in their title."""
    keywords = [k.lower() for k in KEYWORDS]
    for item in items:
        title = item["title"].lower()
        if all(k in title for k in keywords):
            yield item


def publish_items(items: Iterable[Dict[str, str]], dry_run: bool = False) -> None:
    """Publish items or print them in dry-run mode."""
    for item in items:
        if dry_run:
            print(f"[DRY-RUN] Would publish: {item['title']}")
        else:
            print(f"Published: {item['title']}")


def run_once(dry_run: bool = False, use_mock: bool = False) -> None:
    """Run a single iteration of fetching, filtering and publishing."""
    items = fetch_from_sources(use_mock=use_mock)
    items = list(filter_items(items))
    publish_items(items, dry_run=dry_run)


def run_loop(dry_run: bool = False, use_mock: bool = False, interval: int = 60) -> None:
    """Continuously run the bot with a delay between iterations."""
    try:
        while True:
            run_once(dry_run=dry_run, use_mock=use_mock)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("Loop interrupted. Exiting...")

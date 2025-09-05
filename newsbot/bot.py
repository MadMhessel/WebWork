"""Minimal bot logic for newsbot.

These functions are placeholders demonstrating how the CLI might
interact with the rest of the system.
"""

import time
from typing import Iterable, Dict

from .config import KEYWORDS, SOURCES
from . import storage


def fetch_from_sources(use_mock: bool = False) -> Iterable[Dict[str, str]]:
    """Yield dummy items from configured sources."""
    for src in SOURCES:
        if use_mock:
            title = f"Нижегородская область строительство news from {src}"
        else:
            title = f"Fetched news from {src}"
        yield {"title": title, "url": src}


def filter_items(items: Iterable[Dict[str, str]]) -> Iterable[Dict[str, str]]:
    """Filter items that contain all keywords in their title."""
    keywords = [k.lower() for k in KEYWORDS]
    for item in items:
        title = item["title"].lower()
        if all(k in title for k in keywords):
            yield item


def publish_items(items: Iterable[Dict[str, str]], dry_run: bool = False) -> None:
    """Publish items or print them in dry-run mode with deduplication."""
    for item in items:
        url = item.get("url")
        guid = item.get("guid")
        title = item.get("title")

        if storage.is_published(url=url, guid=guid, title=title):
            print(f"[DUP-DB] {title}")
            continue

        if dry_run:
            print(f"[DRY-RUN: READY] {title}")
        else:
            print(f"[PUBLISHED] {title}")
            storage.mark_published(url=url, guid=guid, title=title)


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

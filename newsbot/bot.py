"""Minimal bot logic for newsbot.

These functions are placeholders demonstrating how the CLI might
interact with the rest of the system.
"""

import logging
import time
from typing import Dict, Iterable

from .config import KEYWORDS, SOURCES


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
    """Publish items or print them in dry-run mode."""
    for item in items:
        if dry_run:
            print(f"[DRY-RUN] Would publish: {item['title']}")
        else:
            print(f"Published: {item['title']}")


def run_once(
    dry_run: bool = False, use_mock: bool = False, log_level: str = "INFO"
) -> None:
    """Run a single iteration of fetching, filtering and publishing."""
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))
    items = fetch_from_sources(use_mock=use_mock)
    items = list(filter_items(items))
    publish_items(items, dry_run=dry_run)


def run_loop(
    dry_run: bool = False,
    use_mock: bool = False,
    interval: int = 60,
    log_level: str = "INFO",
) -> None:
    """Continuously run the bot with a delay between iterations."""
    try:
        while True:
            run_once(dry_run=dry_run, use_mock=use_mock, log_level=log_level)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("Loop interrupted. Exiting...")

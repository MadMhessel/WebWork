"""Minimal bot logic for newsbot.

These functions are placeholders demonstrating how the CLI might
interact with the rest of the system.
"""

import asyncio
import os
import time
from typing import Iterable, Dict
from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup

from telegram import Bot
from telegram.error import TelegramError

from .config import KEYWORDS, SOURCES
from . import storage


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
        url = src["url"]
        if use_mock:
            yield {
                "title": f"Нижегородская область строительство news from {src['name']}",
                "url": url,
                "guid": url,
            }
            continue

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"Error fetching {src['name']}: {exc}")
            continue

        feed = feedparser.parse(response.content)
        entries = getattr(feed, "entries", [])

        if entries:
            for entry in entries[:limit]:
                title = entry.get("title", "").strip()
                link = entry.get("link", url).strip()
                guid = entry.get("id") or entry.get("guid") or link
                yield {"title": title, "url": link, "guid": guid}
            continue

        soup = BeautifulSoup(response.text, "html.parser")
        links = soup.find_all("a", href=True)
        for tag in links[:limit]:
            title = tag.get_text(strip=True)
            if not title:
                continue
            link = urljoin(url, tag["href"])
            yield {"title": title, "url": link, "guid": link}


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
            
    """Publish items to a Telegram channel.

    BOT_TOKEN and CHANNEL_ID are read from the environment. When ``dry_run``
    is true, messages are printed instead of being sent. Errors during
    sending are caught and reported.
    """

    token = os.getenv("BOT_TOKEN")
    channel_id = os.getenv("CHANNEL_ID")

    if dry_run or not token or not channel_id:
        for item in items:
            text = f"{item['title']}\n{item['url']}"
            print(f"[DRY-RUN] Would publish: {text}")
        if not token or not channel_id:
            print("BOT_TOKEN or CHANNEL_ID is not set; running in dry-run mode")
        return

    bot = Bot(token=token)

    async def _send_all() -> None:
        for item in items:
            text = f"{item['title']}\n{item['url']}"
            try:
                await bot.send_message(chat_id=channel_id, text=text)
                print(f"Published: {item['title']}")
            except TelegramError as exc:
                print(f"Failed to publish {item['title']}: {exc}")

    asyncio.run(_send_all())


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

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

from .config import (
    CONSTRUCTION_KEYWORDS,
    REGION_KEYWORDS,
    SOURCES,
)
from . import storage


def fetch_from_sources(use_mock: bool = False, limit: int = 10) -> Iterable[Dict[str, str]]:
    """Fetch and yield items from configured sources.

    Each source in ``SOURCES`` is a dictionary with ``type`` and ``url`` keys.
    ``type`` may be ``rss``, ``html_list`` or ``html`` and optional CSS
    selectors can be supplied via the ``selectors`` dictionary.

    When ``use_mock`` is True, mock items are generated without performing
    network requests.
    """

    for src in SOURCES:
        url = src["url"] if isinstance(src, dict) else src
        src_type = src.get("type", "rss") if isinstance(src, dict) else "rss"
        selectors = src.get("selectors", {}) if isinstance(src, dict) else {}

        if use_mock:
            yield {
                "title": f"Нижегородская область строительство news from {url}",
                "url": url,
                "guid": url,
            }
            continue

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"Error fetching {url}: {exc}")
            continue

        if src_type == "rss":
            feed = feedparser.parse(response.content)
            entries = getattr(feed, "entries", [])
            for entry in entries[:limit]:
                title = entry.get("title", "").strip()
                link = entry.get("link", url).strip()
                guid = entry.get("id") or entry.get("guid") or link
                yield {"title": title, "url": link, "guid": guid}
            continue

        soup = BeautifulSoup(response.text, "html.parser")

        if src_type == "html_list":
            item_selector = selectors.get("items", "a")
            for tag in soup.select(item_selector)[:limit]:
                title = tag.get_text(strip=True)
                if not title:
                    continue
                link = urljoin(url, tag.get("href", ""))
                yield {"title": title, "url": link, "guid": link}
        elif src_type == "html":
            title_selector = selectors.get("title")
            link_selector = selectors.get("link")
            title_tag = soup.select_one(title_selector) if title_selector else soup.title
            link_tag = soup.select_one(link_selector) if link_selector else None
            title = title_tag.get_text(strip=True) if title_tag else url
            link = urljoin(url, link_tag.get("href", "")) if link_tag and link_tag.get("href") else url
            yield {"title": title, "url": link, "guid": link}


def filter_items(items: Iterable[Dict[str, str]]) -> Iterable[Dict[str, str]]:
    """Filter items containing regional and construction keywords."""
    region_kw = [k.lower() for k in REGION_KEYWORDS]
    construction_kw = [k.lower() for k in CONSTRUCTION_KEYWORDS]
    for item in items:
        title = item["title"].lower()
        if any(k in title for k in region_kw) and any(
            k in title for k in construction_kw
        ):
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

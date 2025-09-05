import pytest
from newsbot import bot


def test_filter_items():
    items = [
        {"title": "Нижегородская область строительство проект"},
        {"title": "Нижегородская область событие"},
        {"title": "строительство в регионе"},
    ]
    assert list(bot.filter_items(items)) == [{"title": "Нижегородская область строительство проект"}]


def test_fetch_from_sources(monkeypatch):
    fake_sources = ["src1", "src2"]
    monkeypatch.setattr(bot, "SOURCES", fake_sources)
    items = list(bot.fetch_from_sources(use_mock=True))
    expected = [
        {"title": f"Нижегородская область строительство news from {src}", "url": src}
        for src in fake_sources
    ]
    assert items == expected


def test_publish_items_dry_run(capsys):
    items = [
        {"title": "t1"},
        {"title": "t2"},
    ]
    bot.publish_items(items, dry_run=True)
    captured = capsys.readouterr()
    assert "[DRY-RUN] Would publish: t1" in captured.out
    assert "Published" not in captured.out

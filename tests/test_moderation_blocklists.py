import moderation


def test_blocklists_detect_profanity():
    item = {"title": "Хреновый заголовок", "content": "Просто текст"}
    result = moderation.run_blocklists(item)
    assert result.blocked
    assert result.label == "ненормативная лексика"


def test_hold_flags_detect_incident():
    item = {"title": "На стройке погиб рабочий", "content": "Подробности происшествия"}
    flags = moderation.run_hold_flags(item)
    keys = {flag.key for flag in flags}
    assert "heavy_incident" in keys


def test_kazusy_require_quality_note():
    item = {"title": "Травмы на площадке", "rubric": "kazusy"}
    flags = moderation.run_hold_flags(item)
    assert flags
    assert any(flag.requires_quality_note for flag in flags)


def test_kazusy_block_override():
    item = {"title": "Найден труп на объекте", "rubric": "kazusy"}
    result = moderation.run_blocklists(item)
    assert result.blocked

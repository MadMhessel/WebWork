from WebWork import moderation, tagging


def test_block_hold_deprioritize_rules_and_overrides():
    blocked = moderation.run_blocklists({"title": "Жуткая авария"})
    assert blocked.blocked

    kazus_item = {"title": "Произошло обрушение перекрытий", "rubric": "kazusy"}
    hold_flags = moderation.run_hold_flags(kazus_item)
    assert any(flag.key == "kazus_injury" for flag in hold_flags)
    assert all(flag.requires_quality_note for flag in hold_flags)

    promo_item = {
        "title": "Скидки на квартиры до 30%",
        "rubric": "objects",
        "reasons": {"region": True, "topic": True},
    }
    assert not moderation.run_deprioritize_flags(promo_item)

    promo_item.pop("reasons")
    promo_flags = moderation.run_deprioritize_flags(promo_item)
    assert any(flag.key == "promo" for flag in promo_flags)


def test_confirmation_rules_require_sources():
    item = {"title": "Обрушение на стройке", "rubric": "objects"}
    flags = moderation.run_hold_flags(item)
    verdict = moderation.needs_confirmation(item, flags, {"sources": [{"source_domain": "a", "trust_level": 2}]})
    assert verdict.needs_confirmation
    assert verdict.reasons

    trusted_sources = {"sources": [{"source_domain": "a", "trust_level": 3}]}
    verdict_ok = moderation.needs_confirmation(item, flags, trusted_sources)
    assert not verdict_ok.needs_confirmation


def test_tagging_detects_geo_and_categories():
    text = "В Нижегородской области выдано разрешение на строительство новой школы"
    tags, neg = tagging.extract_tags(text)
    assert "#НижегородскаяОбласть" in tags
    assert "#объекты" in tags
    assert not neg

    text2 = "В Дзержинске обрушились перекрытия, а директора назначен новым руководителем"
    tags2, _ = tagging.extract_tags(text2)
    assert "#Дзержинск" in tags2
    assert "#казусы" in tags2
    assert "#персоны" in tags2

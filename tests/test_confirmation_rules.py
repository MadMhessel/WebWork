import moderation


def make_flag(key: str) -> moderation.Flag:
    return moderation.Flag(key=key, pattern=key, label=key)


def test_confirmation_requires_high_trust_for_incident():
    item = {"rubric": "objects"}
    flags = [make_flag("heavy_incident")]
    ctx = {"sources": [{"source_domain": "example.com", "trust_level": 2}], "flags": flags}
    verdict = moderation.check_confirmation_requirements(item, ctx)
    assert verdict.needs_confirmation
    assert verdict.reasons


def test_confirmation_passes_with_trust_level():
    item = {"rubric": "objects"}
    flags = [make_flag("heavy_incident")]
    ctx = {"sources": [{"source_domain": "example.com", "trust_level": 3}], "flags": flags}
    verdict = moderation.check_confirmation_requirements(item, ctx)
    assert not verdict.needs_confirmation


def test_confirmation_objects_requires_official():
    item = {"rubric": "objects"}
    ctx = {
        "sources": [
            {"source_domain": "one.com", "trust_level": 2},
            {"source_domain": "one.com", "trust_level": 2},
        ],
        "flags": [],
    }
    verdict = moderation.check_confirmation_requirements(item, ctx)
    assert verdict.needs_confirmation


def test_confirmation_objects_two_sources_ok():
    item = {"rubric": "objects"}
    ctx = {
        "sources": [
            {"source_domain": "one.com", "trust_level": 2},
            {"source_domain": "two.com", "trust_level": 2},
            {"source_domain": "two.com", "trust_level": 2},
        ],
        "flags": [],
    }
    # ensure two independent domains => ok
    verdict = moderation.check_confirmation_requirements(item, ctx)
    assert not verdict.needs_confirmation

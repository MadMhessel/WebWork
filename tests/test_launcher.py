import os
from pathlib import Path

import pytest

from tools.launcher import (
    build_command,
    discover_profile_file,
    load_env_file,
    mask_value,
    merge_environment,
    parse_kv_pairs,
    read_profiles,
    save_env_file,
)


def test_load_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=bar\nSECRET=top\n", encoding="utf-8")
    values = load_env_file(env_file)
    assert values == {"FOO": "bar", "SECRET": "top"}


def test_save_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    save_env_file(env_file, {"B": "2", "A": "1"})
    content = env_file.read_text(encoding="utf-8").splitlines()
    assert content[0].startswith("# Автоматически")
    assert "A=1" in content
    assert "B=2" in content


def test_merge_environment_preserves_updates() -> None:
    base = {"A": "1"}
    updated = merge_environment(base, {"B": "2", "A": "3"})
    assert updated == {"A": "3", "B": "2"}


@pytest.mark.parametrize(
    "raw,expected",
    [
        ([], {}),
        (["A=1", "B=two"], {"A": "1", "B": "two"}),
    ],
)
def test_parse_kv_pairs_valid(raw, expected) -> None:
    assert parse_kv_pairs(raw) == expected


@pytest.mark.parametrize("raw", [["A"], ["=value"], ["=", "B=2"]])
def test_parse_kv_pairs_invalid(raw) -> None:
    with pytest.raises(ValueError):
        parse_kv_pairs(raw)


def test_build_command_uses_custom_python() -> None:
    command = build_command("main.py", ["--dry"], "/usr/bin/python3")
    assert command == ["/usr/bin/python3", "main.py", "--dry"]


def test_mask_value_hides_secret() -> None:
    assert mask_value("TELEGRAM_BOT_TOKEN", "123") == "*** скрыто ***"
    assert mask_value("VISIBLE", "value") == "value"


def test_read_profiles(tmp_path: Path) -> None:
    profile_file = tmp_path / "profiles.yaml"
    profile_file.write_text("default: {setting: value}\n", encoding="utf-8")
    profiles = read_profiles(profile_file)
    assert "default" in profiles


def test_discover_profile_file_prefers_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profiles_repo = tmp_path / "profiles.yaml"
    profiles_repo.write_text("{default: {}}\n", encoding="utf-8")
    monkeypatch.setenv("NEWSBOT_PROFILE_PATH", str(profiles_repo))
    found = discover_profile_file(config_dir=tmp_path)
    assert found == profiles_repo.resolve()

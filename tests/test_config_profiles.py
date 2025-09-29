from __future__ import annotations

from pathlib import Path

import pytest

from config_profiles import ProfileError, activate_profile


def _write_profiles(tmp_path: Path) -> Path:
    data = """
default:
  settings:
    ENABLE_MODERATION: true
    ONLY_TELEGRAM: false

telegram:
  extends: default
  settings:
    ONLY_TELEGRAM: true
    FETCH_LIMIT_PER_SOURCE:
      value: 15
      override: true

broken:
  settings: []
"""

    path = tmp_path / "profiles.yaml"
    path.write_text(data, encoding="utf-8")
    return path


def test_activate_profile_applies_defaults(tmp_path):
    profile_path = _write_profiles(tmp_path)
    env: dict[str, str] = {}
    activation = activate_profile(
        profile_name="default",
        environ=env,
        search_paths=[profile_path],
    )

    assert activation is not None
    assert env["ENABLE_MODERATION"] == "1"
    assert env["ONLY_TELEGRAM"] == "0"
    assert activation.applied == {
        "ENABLE_MODERATION": "1",
        "ONLY_TELEGRAM": "0",
    }
    assert activation.skipped == {}


def test_activate_profile_respects_existing_env(tmp_path):
    profile_path = _write_profiles(tmp_path)
    env: dict[str, str] = {"ONLY_TELEGRAM": "1"}

    activation = activate_profile(
        profile_name="default",
        environ=env,
        search_paths=[profile_path],
    )

    assert activation is not None
    # Value preserved because override=False
    assert env["ONLY_TELEGRAM"] == "1"
    assert activation.skipped == {"ONLY_TELEGRAM": "1"}


def test_activate_profile_overrides_when_requested(tmp_path):
    profile_path = _write_profiles(tmp_path)
    env: dict[str, str] = {"FETCH_LIMIT_PER_SOURCE": "50"}

    activation = activate_profile(
        profile_name="telegram",
        environ=env,
        search_paths=[profile_path],
    )

    assert activation is not None
    assert env["FETCH_LIMIT_PER_SOURCE"] == "15"
    assert activation.applied["FETCH_LIMIT_PER_SOURCE"] == "15"


def test_activate_profile_invalid_config(tmp_path):
    profile_path = _write_profiles(tmp_path)

    with pytest.raises(ProfileError):
        activate_profile(
            profile_name="broken",
            environ={},
            search_paths=[profile_path],
        )

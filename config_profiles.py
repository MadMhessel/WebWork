"""Profile-driven configuration helpers for NewsBot."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Mapping, MutableMapping, Optional

import yaml

logger = logging.getLogger(__name__)

DEFAULT_PROFILE_NAME = "default"
PROFILE_ENV_VAR = "NEWSBOT_PROFILE"
PROFILE_PATH_ENV_VAR = "NEWSBOT_PROFILE_PATH"
CONFIG_FILE_NAME = "profiles.yaml"


class ProfileError(RuntimeError):
    """Raised when profile configuration is invalid."""


@dataclass(frozen=True)
class ProfileActivation:
    """Information about the applied profile."""

    name: str
    source: Path
    applied: Dict[str, str]
    skipped: Dict[str, str]


def _stringify(value: object) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return ",".join(str(v) for v in value)
    return str(value)


def _load_profiles(path: Path) -> Dict[str, dict]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - pass-through error path
        raise ProfileError(f"Не удалось разобрать {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ProfileError(f"Файл {path} должен содержать словарь профилей")

    # Ensure each entry is a mapping for consistent processing
    for key, value in data.items():
        if value is None:
            data[key] = {}
        elif not isinstance(value, dict):
            raise ProfileError(f"Профиль {key} должен быть словарём, а не {type(value)!r}")

    return data  # type: ignore[return-value]


def _resolve_profile(
    name: str,
    profiles: Mapping[str, dict],
    *,
    stack: Optional[tuple[str, ...]] = None,
) -> dict:
    stack = stack or tuple()
    if name in stack:
        raise ProfileError(
            "Обнаружена циклическая ссылка профилей: " + " → ".join(stack + (name,))
        )

    profile = profiles.get(name)
    if profile is None:
        raise ProfileError(f"Профиль '{name}' не найден")

    parent_name = profile.get("extends")
    settings: dict = {}
    if parent_name:
        settings.update(
            _resolve_profile(parent_name, profiles, stack=stack + (name,))
        )

    raw_settings = profile.get("settings")
    if raw_settings is None:
        # Allow shorthand where settings are defined at the profile level
        raw_settings = {
            key: value
            for key, value in profile.items()
            if key not in {"extends", "description"}
        }

    if not isinstance(raw_settings, dict):
        raise ProfileError(
            f"Настройки профиля '{name}' должны быть словарём, а не {type(raw_settings)!r}"
        )

    settings.update(raw_settings)
    return settings


def _discover_profile_file(
    *,
    explicit_path: Optional[str],
    config_dir: Optional[Path],
    search_paths: Optional[Iterable[Path]] = None,
) -> Optional[Path]:
    candidates: list[Path] = []

    if explicit_path:
        candidates.append(Path(explicit_path).expanduser())

    if search_paths:
        for candidate in search_paths:
            candidate = candidate.expanduser()
            if candidate.is_dir():
                candidates.append(candidate / CONFIG_FILE_NAME)
            else:
                candidates.append(candidate)

    if config_dir:
        candidates.append(config_dir / CONFIG_FILE_NAME)

    default_file = Path(__file__).resolve().with_name(CONFIG_FILE_NAME)
    candidates.append(default_file)

    seen: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.is_file():
            return candidate
    return None


def activate_profile(
    *,
    profile_name: Optional[str] = None,
    environ: Optional[MutableMapping[str, str]] = None,
    config_dir: Optional[Path] = None,
    search_paths: Optional[Iterable[Path]] = None,
) -> Optional[ProfileActivation]:
    """Load and apply a profile to the provided environment mapping."""

    env = environ if environ is not None else os.environ
    explicit_path = env.get(PROFILE_PATH_ENV_VAR)
    profile_name = (
        profile_name
        or env.get(PROFILE_ENV_VAR)
        or env.get("NEWSBOT_MODE")
        or DEFAULT_PROFILE_NAME
    )

    profile_file = _discover_profile_file(
        explicit_path=explicit_path,
        config_dir=config_dir,
        search_paths=search_paths,
    )

    if not profile_file:
        logger.debug("Профиль не найден: отсутствует файл конфигурации профилей")
        return None

    profiles = _load_profiles(profile_file)
    settings = _resolve_profile(profile_name, profiles)

    applied: dict[str, str] = {}
    skipped: dict[str, str] = {}

    for raw_key, raw_value in settings.items():
        if raw_value is None:
            continue

        override = False
        value = raw_value
        if isinstance(raw_value, dict) and "value" in raw_value:
            override = bool(raw_value.get("override", False))
            value = raw_value.get("value")
        if value is None:
            continue

        str_value = _stringify(value)
        key = str(raw_key)

        if override or key not in env:
            env[key] = str_value
            applied[key] = str_value
        else:
            skipped[key] = env[key]

    return ProfileActivation(
        name=profile_name,
        source=profile_file,
        applied=applied,
        skipped=skipped,
    )


__all__ = [
    "ProfileActivation",
    "ProfileError",
    "activate_profile",
    "DEFAULT_PROFILE_NAME",
    "PROFILE_ENV_VAR",
    "PROFILE_PATH_ENV_VAR",
]

from __future__ import annotations

import sys
import importlib.util
from pathlib import Path


def _reload_config_module() -> None:
    for name in [
        "config",
        "webwork",
        "webwork.config",
        "config_defaults",
    ]:
        sys.modules.pop(name, None)


def _import_config_from_path(path: Path):
    repo_root = str(path.parent)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    spec = importlib.util.spec_from_file_location("config", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["config"] = module
    spec.loader.exec_module(module)
    return module


def test_env_file_overrides_profile(monkeypatch, tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    env_path = repo_root / ".env"

    original_env_content = env_path.read_text(encoding="utf-8") if env_path.exists() else None

    profile_path = tmp_path / "profiles.yaml"
    profile_path.write_text(
        """
override:
  settings:
    ENABLE_MODERATION:
      value: true
      override: true
    FETCH_LIMIT_PER_SOURCE:
      value: 15
      override: true
""".strip()
        + "\n",
        encoding="utf-8",
    )

    env_path.write_text(
        """
NEWSBOT_PROFILE=override
ENABLE_MODERATION=false
FETCH_LIMIT_PER_SOURCE=99
""".strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("NEWSBOT_PROFILE_PATH", str(profile_path))

    try:
        _reload_config_module()
        config = _import_config_from_path(repo_root / "config.py")

        assert config.ENABLE_MODERATION is False
        assert config.FETCH_LIMIT_PER_SOURCE == 99
    finally:
        _reload_config_module()
        if original_env_content is None:
            if env_path.exists():
                env_path.unlink()
        else:
            env_path.write_text(original_env_content, encoding="utf-8")

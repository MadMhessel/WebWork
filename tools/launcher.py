"""Interactive launcher for NewsBot pipelines."""

from __future__ import annotations

import argparse
import getpass
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, MutableMapping, Optional

from config_profiles import CONFIG_FILE_NAME, DEFAULT_PROFILE_NAME, PROFILE_PATH_ENV_VAR


def _pip_is_available() -> bool:
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def _ensure_pip() -> None:
    if _pip_is_available():
        return

    try:  # pragma: no branch - зависит от окружения пользователя
        import ensurepip

        ensurepip.bootstrap(upgrade=True)
    except Exception:
        pass

    if _pip_is_available():
        return

    tmp_file = Path(tempfile.gettempdir()) / f"get-pip-{int(time.time())}.py"
    try:
        with urllib.request.urlopen("https://bootstrap.pypa.io/get-pip.py") as src, tmp_file.open(
            "wb"
        ) as dst:
            shutil.copyfileobj(src, dst)
        subprocess.check_call([sys.executable, str(tmp_file)])
    finally:
        try:
            tmp_file.unlink()
        except Exception:
            pass

    if not _pip_is_available():  # pragma: no cover - зависит от окружения пользователя
        raise RuntimeError(
            "pip недоступен в текущем окружении. Установите его вручную и повторите запуск."
        )


def _ensure_dependency(module_name: str, package_spec: str):
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError:
        _ensure_pip()
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package_spec])
        except subprocess.CalledProcessError as exc:  # pragma: no cover - зависит от окружения пользователя
            raise RuntimeError(
                f"Не удалось автоматически установить зависимость {package_spec}."
            ) from exc
        return importlib.import_module(module_name)


dotenv_module = _ensure_dependency("dotenv", "python-dotenv>=1.0.0")
platformdirs_module = _ensure_dependency("platformdirs", "platformdirs>=4.0.0")
yaml = _ensure_dependency("yaml", "PyYAML")

dotenv_values = dotenv_module.dotenv_values
user_config_dir = platformdirs_module.user_config_dir


@dataclass
class Prompt:
    """Description of an interactive prompt."""

    key: str
    question: str
    required: bool = False
    secret: bool = False

    def ask(self, existing: str | None) -> str:
        """Request a value from stdin, returning the provided or existing value."""

        default = existing or ""
        suffix = " (обязательно)" if self.required and not default else ""
        display_default = "<скрыто>" if self.secret and default else default
        while True:
            prompt = f"{self.question}{suffix}"
            if display_default:
                prompt += f" [по умолчанию: {display_default}]"
            prompt += ": "
            raw = (
                getpass.getpass(prompt)
                if self.secret
                else input(prompt)
            ).strip()

            if raw:
                return raw

            if default:
                return default

            if not self.required:
                return ""

            print("Значение обязательно. Пожалуйста, повторите ввод.")


MANDATORY_PROMPTS: tuple[Prompt, ...] = (
    Prompt("TELEGRAM_BOT_TOKEN", "Telegram Bot API токен", required=True, secret=True),
    Prompt("CHANNEL_TEXT_CHAT_ID", "ID канала для текстов", required=True),
    Prompt("CHANNEL_MEDIA_CHAT_ID", "ID канала для медиа", required=True),
    Prompt("TELETHON_API_ID", "Telethon api_id", required=True),
    Prompt("TELETHON_API_HASH", "Telethon api_hash", required=True, secret=True),
)

OPTIONAL_PROMPTS: tuple[Prompt, ...] = (
    Prompt("TELETHON_SESSION_NAME", "Имя файла сессии Telethon"),
    Prompt("SUGGEST_BOT_TOKEN", "Токен бота-приёмной", secret=True),
    Prompt("SUGGEST_MOD_CHAT_ID", "Чат модераторов приёмной"),
    Prompt("REVIEW_CHAT_ID", "Чат модераторов основного потока"),
    Prompt("RAW_REVIEW_CHAT_ID", "Чат для RAW-потока"),
    Prompt("NEWSBOT_PROFILE", "Профиль конфигурации"),
)

SECRET_KEYS = {prompt.key for prompt in MANDATORY_PROMPTS if prompt.secret} | {
    prompt.key for prompt in OPTIONAL_PROMPTS if prompt.secret
}


def load_env_file(path: Path) -> dict[str, str]:
    """Parse environment variables from the provided .env file."""

    if not path.is_file():
        return {}
    values = dotenv_values(path)
    return {k: v for k, v in values.items() if v is not None}


def save_env_file(path: Path, values: Mapping[str, str]) -> None:
    """Persist environment variables to disk."""

    lines = [
        "# Автоматически сгенерировано tools/launcher.py",
        "# Секреты скрыты в выводе, но присутствуют в файле.",
    ]
    for key in sorted(values):
        value = values[key]
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def discover_profile_file(*, config_dir: Path) -> Optional[Path]:
    """Locate profiles.yaml according to configuration rules."""

    candidates: list[Path] = []

    explicit = os.getenv(PROFILE_PATH_ENV_VAR)
    if explicit:
        candidates.append(Path(explicit).expanduser())

    candidates.append(config_dir / CONFIG_FILE_NAME)

    repo_profiles = Path(__file__).resolve().parents[1] / CONFIG_FILE_NAME
    candidates.append(repo_profiles)

    cwd_profiles = Path.cwd() / CONFIG_FILE_NAME
    candidates.append(cwd_profiles)

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file():
            return resolved
    return None


def read_profiles(path: Path) -> dict[str, dict]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise RuntimeError("profiles.yaml должен содержать словарь профилей")
    return {str(k): dict(v or {}) for k, v in raw.items()}


def choose_profile(available: Iterable[str], current: str | None) -> str | None:
    choices = sorted(set(available))
    if not choices:
        return current
    print("\nДоступные профили: ")
    for name in choices:
        marker = "*" if current and name == current else "-"
        print(f"  {marker} {name}")
    while True:
        raw = input(
            "Выберите профиль (Enter, чтобы оставить без изменений): "
        ).strip()
        if not raw:
            return current
        if raw in choices:
            return raw
        print("Профиль не найден. Пожалуйста, выберите из списка.")


def prompt_settings(existing: Mapping[str, str]) -> dict[str, str]:
    print(
        "Введите ключи и параметры подключения. "
        "Оставьте поле пустым, чтобы сохранить текущее значение."
    )
    result: dict[str, str] = {}
    for prompt in MANDATORY_PROMPTS + OPTIONAL_PROMPTS:
        current = existing.get(prompt.key)
        value = prompt.ask(current)
        if value:
            result[prompt.key] = value
        elif current:
            result[prompt.key] = current
    return result


def mask_value(key: str, value: str) -> str:
    if key in SECRET_KEYS and value:
        return "*** скрыто ***"
    if len(value) > 80:
        return value[:77] + "..."
    return value


def build_command(script: str, extra_args: Iterable[str], python_executable: str) -> list[str]:
    return [python_executable, script, *extra_args]


def merge_environment(
    base: MutableMapping[str, str], updates: Mapping[str, str]
) -> MutableMapping[str, str]:
    for key, value in updates.items():
        if value is not None:
            base[key] = value
    return base


def parse_kv_pairs(pairs: Iterable[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in pairs:
        if "=" not in raw:
            raise ValueError(f"Некорректный формат переменной: '{raw}'. Ожидается KEY=VALUE")
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError("Имя переменной не может быть пустым")
        result[key] = value
    return result


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Интерактивный запуск NewsBot с настройкой окружения",
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path(user_config_dir("NewsBot")),
        help="Каталог для сохранения .env (по умолчанию используется каталог пользователя)",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Явный путь к .env. По умолчанию ~/.config/NewsBot/.env",
    )
    parser.add_argument(
        "--script",
        default="main.py",
        help="Скрипт для запуска (main.py, raw_pipeline.py и т.п.)",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Исполняемый файл Python",
    )
    parser.add_argument(
        "--set",
        dest="extra",
        nargs="*",
        default=(),
        help="Дополнительные переменные окружения в формате KEY=VALUE",
    )
    parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="Только вывести доступные профили и завершить работу",
    )
    parser.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="Аргументы, передаваемые целевому скрипту",
    )

    args_ns = parser.parse_args(list(argv) if argv is not None else None)

    config_dir: Path = args_ns.config_dir
    env_file: Path = args_ns.env_file or (config_dir / ".env")
    config_dir.mkdir(parents=True, exist_ok=True)

    stored_env = load_env_file(env_file)

    profile_file = discover_profile_file(config_dir=config_dir)
    available_profiles: list[str] = []
    if profile_file:
        profiles_data = read_profiles(profile_file)
        available_profiles = list(profiles_data.keys())

    if args_ns.list_profiles:
        if profile_file and available_profiles:
            print(f"Файл профилей: {profile_file}")
            for name in sorted(available_profiles):
                print(f" - {name}")
        else:
            print("Профили не найдены.")
        return 0

    updates = prompt_settings(stored_env)

    if available_profiles:
        current_profile = updates.get("NEWSBOT_PROFILE") or stored_env.get("NEWSBOT_PROFILE") or DEFAULT_PROFILE_NAME
        selected = choose_profile(available_profiles, current_profile)
        if selected:
            updates["NEWSBOT_PROFILE"] = selected

    if args_ns.extra:
        try:
            extra_pairs = parse_kv_pairs(args_ns.extra)
        except ValueError as exc:
            parser.error(str(exc))
        updates.update(extra_pairs)

    runtime_env = merge_environment(os.environ.copy(), updates)
    file_env = stored_env.copy()
    file_env.update({k: v for k, v in updates.items() if not k.startswith("_")})

    save_env_file(env_file, file_env)

    print("\nПараметры запуска:")
    for key, value in sorted(updates.items()):
        print(f"  {key} = {mask_value(key, value)}")

    extra_args = list(args_ns.args or [])
    if extra_args and extra_args[0] == "--":
        extra_args = extra_args[1:]

    command = build_command(args_ns.script, extra_args, args_ns.python)
    print("\nЗапуск: ", " ".join(command))

    completed = subprocess.run(command, env=runtime_env, check=False)
    return completed.returncode


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())

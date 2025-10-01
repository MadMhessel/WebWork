import os
import sys
import io
import re
import json
import shlex
import time
import queue
import shutil
import traceback
import zipfile
import tempfile
import threading
import subprocess
import importlib
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

APP_NAME = "WebWork Manager"
APP_VERSION = "3.0"
CFG_FILE = Path.home() / ".webwork_manager.json"  # хранение настроек (url, ветка и т.д.)
ERROR_LOG_FILE = Path.home() / "webwork_autostart_error.log"


def _guess_repo_dir() -> Path | None:
    here = Path(__file__).resolve().parent
    candidates = [here, here.parent]
    sentinels = {"main.py", "sources_nn.yaml", "requirements.txt"}

    for base in candidates:
        if any((base / sentinel).exists() for sentinel in sentinels):
            return base
    return None


def _fatal_error(message: str, exc: BaseException | None = None) -> "NoReturn":
    """Записывает ошибку в лог и пытается показать пользователю понятное сообщение."""

    log_note = ""
    details = ""
    if exc is not None:
        details = "".join(traceback.format_exception(exc))

    try:
        with ERROR_LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n")
            if details:
                fh.write(details)
            fh.write("\n")
        log_note = f"\n\nПолный текст ошибки сохранён в {ERROR_LOG_FILE}"
    except Exception:
        log_note = ""

    display_text = message + log_note
    if exc is not None and not log_note:
        display_text += f"\n\n{exc}"

    shown = False
    tk_module = globals().get("tk")
    if tk_module and hasattr(tk_module, "Tk"):
        try:
            root = tk_module.Tk()
            root.withdraw()
            messagebox.showerror(APP_NAME, display_text)
            root.destroy()
            shown = True
        except Exception:
            shown = False

    if not shown and os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, display_text, APP_NAME, 0x10)
            shown = True
        except Exception:
            shown = False

    if not shown:
        sys.stderr.write(display_text + "\n")
        try:
            if sys.stdin.isatty():
                input("Нажмите Enter для выхода...")
        except Exception:
            pass

    raise SystemExit(1)


try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk
except Exception as exc:  # pragma: no cover - зависит от окружения пользователя
    _fatal_error(
        "Не удалось загрузить модуль tkinter. Установите поддержку Tkinter и повторите запуск.",
        exc,
    )

def _ensure_dependency(module_name: str, package_name: str, friendly_name: str):
    """Гарантирует наличие зависимости. При необходимости пытается установить через pip."""

    try:
        return importlib.import_module(module_name)
    except Exception:
        install_cmd = [sys.executable, "-m", "pip", "install", package_name]
        try:
            subprocess.check_call(install_cmd)
        except Exception as exc:  # pragma: no cover - зависит от окружения пользователя
            cmd_display = " ".join(shlex.quote(x) for x in install_cmd)
            _fatal_error(
                "Не удалось загрузить модуль "
                f"{friendly_name}. Автоматическая установка через pip завершилась ошибкой.\n"
                f"Попробуйте вручную выполнить команду: {cmd_display}",
                exc,
            )
        try:
            return importlib.import_module(module_name)
        except Exception as exc:  # pragma: no cover - зависит от окружения пользователя
            _fatal_error(
                "Не удалось загрузить модуль "
                f"{friendly_name} даже после установки. Проверьте окружение и повторите запуск.",
                exc,
            )


yaml = _ensure_dependency("yaml", "PyYAML", "PyYAML (yaml)")

# --- ключи окружения (см. v2) ---
DEFAULT_ENV_KEYS = [
    ("TELEGRAM_MODE", "BOT_API"),          # BOT_API | MTPROTO | WEB
    ("TELEGRAM_BOT_TOKEN", ""),
    ("CHANNEL_CHAT_ID", ""),
    ("REVIEW_CHAT_ID", ""),
    ("PARSE_MODE", "HTML"),
    ("DRY_RUN", "false"),
    ("CAPTION_LIMIT", "1024"),
    # MTProto (поддерживаем 2 варианта имён, чтобы покрыть разные проекты)
    ("TG_API_ID", ""),
    ("TG_API_HASH", ""),
    ("TG_SESSION_FILE", ""),
    ("TG_SESSION_STRING", ""),
    ("TELETHON_API_ID", ""),   # альтернативные ключи
    ("TELETHON_API_HASH", ""),
    # RAW/дедуп/модерация
    ("ENABLE_MODERATION", "false"),
    ("NEAR_DUPLICATES_ENABLED", "false"),
    ("NEAR_DUPLICATE_THRESHOLD", "0.9"),
    ("RAW_STREAM_ENABLED", "false"),
    ("RAW_REVIEW_CHAT_ID", ""),
    ("RAW_BYPASS_FILTERS", "false"),
    ("RAW_BYPASS_DEDUP", "false"),
    ("RAW_FORWARD_STRATEGY", "copy"),
    # HTTP
    ("HTTP_TIMEOUT", "10"),
    ("HTTP_TIMEOUT_CONNECT", "5"),
    ("HTTP_RETRY_TOTAL", "3"),
    ("HTTP_BACKOFF", "0.5"),
    # Раздельные каналы (если проект их поддерживает)
    ("CHANNEL_TEXT_CHAT_ID", ""),
    ("CHANNEL_MEDIA_CHAT_ID", ""),
]

ENV_BOOL_KEYS = {
    "DRY_RUN",
    "ENABLE_MODERATION",
    "NEAR_DUPLICATES_ENABLED",
    "RAW_STREAM_ENABLED",
    "RAW_BYPASS_FILTERS",
    "RAW_BYPASS_DEDUP",
}

ENV_INT_KEYS = {
    "CAPTION_LIMIT",
    "TG_API_ID",
    "TELETHON_API_ID",
    "HTTP_TIMEOUT",
    "HTTP_TIMEOUT_CONNECT",
    "HTTP_RETRY_TOTAL",
}

ENV_FLOAT_KEYS = {
    "NEAR_DUPLICATE_THRESHOLD",
    "HTTP_BACKOFF",
}

ENV_SCHEMA = {
    "type": "object",
    "properties": {
        "TELEGRAM_MODE": {"type": "string", "enum": ["BOT_API", "MTPROTO", "WEB"]},
        "CHANNEL_CHAT_ID": {"type": "string", "minLength": 1},
        "CHANNEL_TEXT_CHAT_ID": {"type": "string"},
        "CHANNEL_MEDIA_CHAT_ID": {"type": "string"},
        "TG_API_ID": {"type": "integer"},
        "TG_API_HASH": {"type": "string", "minLength": 1},
        "TG_SESSION_FILE": {"type": "string"},
        "TG_SESSION_STRING": {"type": "string"},
        "TELETHON_API_ID": {"type": "integer"},
        "TELETHON_API_HASH": {"type": "string", "minLength": 1},
        "TELEGRAM_BOT_TOKEN": {"type": "string", "minLength": 1},
        "NEAR_DUPLICATE_THRESHOLD": {"type": "number"},
        "NEAR_DUPLICATES_ENABLED": {"type": "boolean"},
        "ENABLE_MODERATION": {"type": "boolean"},
        "RAW_STREAM_ENABLED": {"type": "boolean"},
        "RAW_REVIEW_CHAT_ID": {"type": "string"},
        "RAW_BYPASS_FILTERS": {"type": "boolean"},
        "RAW_BYPASS_DEDUP": {"type": "boolean"},
        "RAW_FORWARD_STRATEGY": {"type": "string", "enum": ["copy", "forward", "link"]},
        "HTTP_TIMEOUT": {"type": "integer", "minimum": 0},
        "HTTP_TIMEOUT_CONNECT": {"type": "integer", "minimum": 0},
        "HTTP_RETRY_TOTAL": {"type": "integer", "minimum": 0},
        "HTTP_BACKOFF": {"type": "number", "minimum": 0},
    },
    "required": ["TELEGRAM_MODE"],
    "allOf": [
        {
            "if": {"properties": {"TELEGRAM_MODE": {"const": "BOT_API"}}},
            "then": {"required": ["TELEGRAM_BOT_TOKEN", "CHANNEL_CHAT_ID"]},
        },
        {
            "if": {"properties": {"TELEGRAM_MODE": {"const": "MTPROTO"}}},
            "then": {
                "anyOf": [
                    {"required": ["TG_API_ID", "TG_API_HASH"]},
                    {"required": ["TELETHON_API_ID", "TELETHON_API_HASH"]},
                ]
            },
        },
    ],
}

YAML_SCHEMAS = {
    "sources_nn.yaml": {
        "type": "object",
        "properties": {
            "version": {"type": "integer"},
            "region": {"type": "string"},
            "defaults": {"type": "object"},
            "sources": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "url", "type", "source_domain"],
                    "properties": {
                        "name": {"type": "string", "minLength": 1},
                        "url": {"type": "string", "format": "uri"},
                        "type": {"type": "string"},
                        "source_domain": {"type": "string", "minLength": 1},
                    },
                },
            },
        },
        "required": ["sources"],
    }
}

def load_env_file(path: Path) -> dict:
    env = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env

def dump_env(env: dict) -> str:
    lines = []
    for k, v in env.items():
        if v is None or str(v) == "":
            continue
        lines.append(f"{k}={v}")
    return "\n".join(lines) + "\n"

def merge_with_defaults(env: dict) -> dict:
    merged = {}
    for key, default in DEFAULT_ENV_KEYS:
        merged[key] = env.get(key, default)
    # прочие ключи тоже переносим
    for k, v in env.items():
        if k not in merged:
            merged[k] = v
    # Нормализация возможной опечатки старых env
    if "NEAR_DUPLICTES_ENABLED" in merged and "NEAR_DUPLICATES_ENABLED" not in merged:
        merged["NEAR_DUPLICATES_ENABLED"] = merged["NEAR_DUPLICTES_ENABLED"]
    return merged

# ---------------- Процесс-раннер ----------------
class ProcessRunner:
    def __init__(self, on_output, on_state_change):
        self.proc: subprocess.Popen | None = None
        self.on_output = on_output
        self.on_state_change = on_state_change
        self.stdout_q = queue.Queue()
        self.stderr_q = queue.Queue()
        self.stop_event = threading.Event()

    def start(self, cmd_list, cwd=None, env=None):
        if self.proc and self.proc.poll() is None:
            raise RuntimeError("Процесс уже запущен")
        self.stop_event.clear()
        try:
            self.proc = subprocess.Popen(
                cmd_list,
                cwd=cwd or None,
                env=env or None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
                universal_newlines=True
            )
        except FileNotFoundError as e:
            raise RuntimeError(f"Не удалось запустить: {e}")

        def reader(stream, q):
            with stream:
                for line in stream:
                    if self.stop_event.is_set():
                        break
                    q.put(line)

        threading.Thread(target=reader, args=(self.proc.stdout, self.stdout_q), daemon=True).start()
        threading.Thread(target=reader, args=(self.proc.stderr, self.stderr_q), daemon=True).start()
        threading.Thread(target=self._waiter, daemon=True).start()
        self.on_state_change("running")

    def _waiter(self):
        if not self.proc:
            return
        self.proc.wait()
        code = self.proc.returncode
        self.on_state_change("stopped", code)

    def poll(self):
        items = []
        while True:
            try:
                items.append(("stdout", self.stdout_q.get_nowait()))
            except queue.Empty:
                break
        while True:
            try:
                items.append(("stderr", self.stderr_q.get_nowait()))
            except queue.Empty:
                break
        if items:
            self.on_output(items)

    def terminate(self, kill_after: float = 3.0):
        if not self.proc or self.proc.poll() is not None:
            return
        try:
            self.proc.terminate()
        except Exception:
            pass
        t0 = time.time()
        while time.time() - t0 < kill_after:
            if self.proc.poll() is not None:
                break
            time.sleep(0.1)
        if self.proc.poll() is None:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.stop_event.set()

# ---------------- Текстовый редактор ----------------
class TextEditor(tk.Toplevel):
    def __init__(self, master, filepath: Path):
        super().__init__(master)
        self.title(f"Редактор — {filepath.name}")
        self.geometry("860x620")
        self.filepath = filepath

        self.text = tk.Text(self, wrap="none")
        self.text.pack(fill="both", expand=True)

        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Сохранить", command=self.save).pack(side="left", padx=4, pady=4)
        ttk.Button(toolbar, text="Перезагрузить", command=self.reload).pack(side="left", padx=4, pady=4)

        self.reload()

    def reload(self):
        try:
            content = self.filepath.read_text(encoding="utf-8")
        except FileNotFoundError:
            content = ""
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)

    def save(self):
        content = self.text.get("1.0", "end")
        try:
            self.filepath.write_text(content, encoding="utf-8")
            messagebox.showinfo(APP_NAME, f"Сохранено: {self.filepath}")
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Ошибка сохранения: {e}")


# ---------------- Прокручиваемые контейнеры ----------------
class ScrollableFrame(ttk.Frame):
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        vbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.inner = ttk.Frame(canvas)

        self.inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        window_id = canvas.create_window((0, 0), window=self.inner, anchor="nw")
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfigure(window_id, width=e.width),
        )
        canvas.configure(yscrollcommand=vbar.set)

        canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")

        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)


# ---------------- Основное приложение ----------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry("1180x780")
        self.minsize(1040, 680)

        self.repo_dir: Path | None = None
        self.repo_dir_var = tk.StringVar(value="")
        self.env: dict[str, str] = {}
        self.runner = ProcessRunner(self.on_output, self.on_state_change)
        self.cfg = self._load_cfg()
        self.secret_entries: dict[str, tuple[tk.Entry, ttk.Button]] = {}
        self.var_profile = tk.StringVar(value="")
        self._last_search_pos = "1.0"
        self._psutil_last_update = 0.0
        self._net_io_start: tuple[float, float] | None = None
        self.active_profile: str | None = None
        self._psutil_failed = False
        self.repeat_job_id: str | None = None
        self.repeat_enabled = tk.BooleanVar(value=False)
        self.repeat_minutes = tk.IntVar(value=15)

        self._build_ui()
        self._on_repeat_toggle()
        guessed = _guess_repo_dir()
        if guessed:
            self.repo_dir = guessed
            self.repo_dir_var.set(str(guessed))
            self._refresh_profiles()
        self.after(100, self._tick)

    # ---------- UI ----------
    def _build_ui(self):
        # ВЕРХ
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Папка репозитория WebWork:").pack(side="left")
        self.repo_entry = ttk.Entry(top, width=60, textvariable=self.repo_dir_var)
        self.repo_entry.pack(side="left", padx=6, fill="x", expand=True)
        ttk.Button(top, text="Выбрать…", command=self._choose_repo).pack(side="left")
        ttk.Button(top, text="Открыть в проводнике", command=self._open_repo).pack(side="left", padx=(6,0))

        # Вкладки
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=(0,8))

        self.tab_env = ttk.Frame(self.nb)
        self.tab_run = ttk.Frame(self.nb)
        self.tab_edit = ttk.Frame(self.nb)
        self.tab_update = ttk.Frame(self.nb)

        self.nb.add(self.tab_env, text="Настройка .env")
        self.nb.add(self.tab_run, text="Запуск и логи")
        self.nb.add(self.tab_edit, text="Редактор YAML")
        self.nb.add(self.tab_update, text="Обновления (GitHub)")

        self._build_tab_env()
        self._build_tab_run()
        self._build_tab_edit()
        self._build_tab_update()

    def _sanitize_profile_name(self, name: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", name.strip())
        return cleaned[:64]

    def _profiles_dir(self, ensure: bool = False) -> Path:
        if not self._ensure_repo():
            raise RuntimeError("Репозиторий не выбран")
        path = self.repo_dir / ".env.profiles"
        if ensure:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def _profile_path(self, name: str, ensure_dir: bool = False) -> Path:
        directory = self._profiles_dir(ensure=ensure_dir)
        return directory / f"{name}.env"

    def _refresh_profiles(self):
        if not hasattr(self, "cb_profile"):
            return
        values: list[str] = []
        if self.repo_dir and (self.repo_dir / ".env.profiles").exists():
            for path in sorted((self.repo_dir / ".env.profiles").glob("*.env")):
                values.append(path.stem)
        self.cb_profile.configure(values=values)
        if self.active_profile and self.active_profile in values:
            self.var_profile.set(self.active_profile)
        elif self.var_profile.get() not in values:
            self.var_profile.set(values[0] if values else "")

    def _apply_env_to_fields(self, env: dict[str, str]):
        merged = merge_with_defaults(env)
        self.env = merged
        for k, var in self.fields.items():
            var.set(self.env.get(k, ""))

    def _gather_env_values(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for k, var in self.fields.items():
            val = var.get().strip()
            if val:
                values[k] = val
        for k, v in self.env.items():
            if k not in values and v:
                values[k] = v
        return values

    def _write_env_to_path(self, path: Path, values: dict[str, str]) -> None:
        cleaned = {k: str(v) for k, v in values.items() if v is not None and str(v) != ""}
        if path.parent and not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump_env(cleaned), encoding="utf-8")

    # ---- Tab ENV ----
    def _build_tab_env(self):
        container = ScrollableFrame(self.tab_env)
        container.pack(fill="both", expand=True)
        frm = container.inner
        frm.columnconfigure(1, weight=1)
        frm.columnconfigure(2, weight=0)
        frm.columnconfigure(3, weight=1)
        row = 0

        prof_bar = ttk.Frame(frm)
        prof_bar.grid(row=row, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        ttk.Label(prof_bar, text="Профиль:").pack(side="left", padx=(0, 4))
        self.cb_profile = ttk.Combobox(
            prof_bar,
            textvariable=self.var_profile,
            values=[],
            width=24,
            state="readonly",
        )
        self.cb_profile.pack(side="left")
        self.cb_profile.bind("<<ComboboxSelected>>", lambda _event: self._load_profile())
        ttk.Button(prof_bar, text="Загрузить профиль", command=self._load_profile).pack(side="left", padx=4)
        ttk.Button(prof_bar, text="Сохранить профиль", command=self._save_profile).pack(side="left", padx=4)
        ttk.Button(prof_bar, text="Новый профиль", command=self._new_profile).pack(side="left", padx=4)
        ttk.Button(prof_bar, text="Дублировать", command=self._duplicate_profile).pack(side="left", padx=4)
        row += 1

        ttk.Separator(frm).grid(row=row, column=0, columnspan=4, sticky="ew", pady=6); row += 1

        bbar = ttk.Frame(frm)
        bbar.grid(row=row, column=0, columnspan=4, sticky="ew", pady=(0, 6))
        ttk.Button(bbar, text="Загрузить из .env", command=self._load_env).pack(side="left", padx=4)
        ttk.Button(
            bbar,
            text="Загрузить из .env.example",
            command=lambda: self._load_env(example=True),
        ).pack(side="left", padx=4)
        ttk.Button(bbar, text="Сохранить в .env", command=self._save_env).pack(side="left", padx=4)
        ttk.Button(bbar, text="Проверить заполнение", command=self._validate_env).pack(side="left", padx=4)
        row += 1

        ttk.Separator(frm).grid(row=row, column=0, columnspan=4, sticky="ew", pady=6); row += 1
        self.fields = {}

        def add_field(label, key, values=None, hint="", secret=False):
            nonlocal row
            ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=4)
            if values:
                var = tk.StringVar()
                cb = ttk.Combobox(frm, textvariable=var, values=values, state="readonly")
                cb.grid(row=row, column=1, columnspan=2, sticky="ew", padx=6, pady=4)
                self.fields[key] = var
                hint_col = 3
            else:
                var = tk.StringVar()
                ent = ttk.Entry(frm, textvariable=var, show="•" if secret else "")
                ent.grid(row=row, column=1, sticky="ew", padx=6, pady=4)
                if secret:
                    toggle = ttk.Button(
                        frm,
                        text="👁",
                        width=3,
                        command=lambda k=key: self._toggle_secret(k),
                    )
                    toggle.grid(row=row, column=2, sticky="w", padx=(0, 4))
                    self.secret_entries[key] = (ent, toggle)
                    hint_col = 3
                else:
                    hint_col = 2
                self.fields[key] = var
            if hint:
                ttk.Label(frm, text=hint, foreground="#555").grid(
                    row=row, column=hint_col, sticky="w", padx=(4, 0)
                )
            row += 1

        # Режим
        add_field("TELEGRAM_MODE", "TELEGRAM_MODE", values=["BOT_API", "MTPROTO", "WEB"], hint="Способ отправки")

        ttk.Separator(frm).grid(row=row, column=0, columnspan=4, sticky="ew", pady=6); row += 1

        # Bot API
        ttk.Label(frm, text="Bot API", font=("", 10, "bold")).grid(row=row, column=0, sticky="w", padx=6); row += 1
        add_field("TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN", hint="Токен бота", secret=True)
        add_field("CHANNEL_CHAT_ID", "CHANNEL_CHAT_ID", hint="@alias или -100...")
        add_field("REVIEW_CHAT_ID", "REVIEW_CHAT_ID", hint="для модерации/RAW")
        add_field("PARSE_MODE", "PARSE_MODE", values=["HTML", "MarkdownV2"])
        add_field("DRY_RUN", "DRY_RUN", values=["false", "true"])
        add_field("CAPTION_LIMIT", "CAPTION_LIMIT")

        ttk.Separator(frm).grid(row=row, column=0, columnspan=4, sticky="ew", pady=6); row += 1

        # MTProto
        ttk.Label(frm, text="Telegram API (MTProto)", font=("", 10, "bold")).grid(row=row, column=0, sticky="w", padx=6); row += 1
        add_field("TG_API_ID", "TG_API_ID", hint="или TELETHON_API_ID")
        add_field("TG_API_HASH", "TG_API_HASH", hint="или TELETHON_API_HASH", secret=True)
        add_field("TG_SESSION_FILE", "TG_SESSION_FILE", hint="путь к .session (опц.)")
        add_field("TG_SESSION_STRING", "TG_SESSION_STRING", hint="строка-сессия (опц.)", secret=True)

        ttk.Separator(frm).grid(row=row, column=0, columnspan=4, sticky="ew", pady=6); row += 1

        # Раздельные чаты
        ttk.Label(frm, text="Раздельные чаты (если используются)", font=("", 10, "bold")).grid(row=row, column=0, sticky="w", padx=6); row += 1
        add_field("CHANNEL_TEXT_CHAT_ID", "CHANNEL_TEXT_CHAT_ID", hint="@alias или -100...")
        add_field("CHANNEL_MEDIA_CHAT_ID", "CHANNEL_MEDIA_CHAT_ID", hint="@alias или -100...")

        ttk.Separator(frm).grid(row=row, column=0, columnspan=4, sticky="ew", pady=6); row += 1

        # Модерация/RAW/HTTP
        ttk.Label(frm, text="Модерация/RAW/Дедуп/HTTP", font=("", 10, "bold")).grid(row=row, column=0, sticky="w", padx=6); row += 1
        add_field("ENABLE_MODERATION", "ENABLE_MODERATION", values=["false", "true"])
        add_field("NEAR_DUPLICATES_ENABLED", "NEAR_DUPLICATES_ENABLED", values=["false", "true"])
        add_field("NEAR_DUPLICATE_THRESHOLD", "NEAR_DUPLICATE_THRESHOLD")
        add_field("RAW_STREAM_ENABLED", "RAW_STREAM_ENABLED", values=["false", "true"])
        add_field("RAW_REVIEW_CHAT_ID", "RAW_REVIEW_CHAT_ID")
        add_field("RAW_BYPASS_FILTERS", "RAW_BYPASS_FILTERS", values=["false", "true"])
        add_field("RAW_BYPASS_DEDUP", "RAW_BYPASS_DEDUP", values=["false", "true"])
        add_field("RAW_FORWARD_STRATEGY", "RAW_FORWARD_STRATEGY", values=["copy", "forward", "link"])
        add_field("HTTP_TIMEOUT", "HTTP_TIMEOUT")
        add_field("HTTP_TIMEOUT_CONNECT", "HTTP_TIMEOUT_CONNECT")
        add_field("HTTP_RETRY_TOTAL", "HTTP_RETRY_TOTAL")
        add_field("HTTP_BACKOFF", "HTTP_BACKOFF")

    def _toggle_secret(self, key: str):
        pair = self.secret_entries.get(key)
        if not pair:
            return
        entry, button = pair
        current = entry.cget("show")
        if current:
            entry.configure(show="")
            button.configure(text="🙈")
        else:
            entry.configure(show="•")
            button.configure(text="👁")

    # ---- Tab RUN ----
    def _build_tab_run(self):
        frm = self.tab_run
        frm.rowconfigure(2, weight=1)
        frm.columnconfigure(0, weight=1)

        controls = ttk.Frame(frm, padding=(4,6))
        controls.grid(row=0, column=0, sticky="ew")
        ttk.Button(controls, text="Запустить", command=self._start_bot).pack(side="left", padx=4)
        ttk.Button(controls, text="Остановить", command=self._stop_bot).pack(side="left", padx=4)
        ttk.Button(controls, text="Очистить лог", command=lambda: self._set_logs("")).pack(side="left", padx=4)

        ttk.Checkbutton(
            controls,
            text="Повторять",
            variable=self.repeat_enabled,
            command=self._on_repeat_toggle,
        ).pack(side="left", padx=(12, 4))
        ttk.Label(controls, text="каждые").pack(side="left", padx=(0, 2))
        self.spin_repeat = ttk.Spinbox(
            controls,
            from_=1,
            to=1440,
            textvariable=self.repeat_minutes,
            width=5,
        )
        self.spin_repeat.pack(side="left")
        ttk.Label(controls, text="мин.").pack(side="left", padx=(2, 4))

        ttk.Separator(controls, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Button(
            controls,
            text="Только RAW",
            command=lambda: self._start_with_args(["--only-raw"]),
        ).pack(side="left", padx=4)
        ttk.Button(
            controls,
            text="Без RAW",
            command=lambda: self._start_with_args(["--no-raw"]),
        ).pack(side="left", padx=4)

        ttk.Separator(controls, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Button(controls, text="Создать venv", command=self._create_venv).pack(side="left", padx=4)
        ttk.Button(controls, text="Установить зависимости", command=self._install_requirements).pack(side="left", padx=4)
        ttk.Button(controls, text="Проверить getMe", command=self._check_getme).pack(side="left", padx=4)
        ttk.Button(controls, text="Проверить MTProto", command=self._check_telethon_login).pack(side="left", padx=4)

        ttk.Separator(controls, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Button(controls, text="Установить Telethon", command=self._install_telethon).pack(side="left", padx=4)
        ttk.Button(controls, text="Проверка окружения", command=self._env_check).pack(side="left", padx=4)
        ttk.Button(controls, text="Сетевой тест", command=self._network_test).pack(side="left", padx=4)

        ttk.Label(controls, text="Статус:").pack(side="left", padx=(16,4))
        self.lbl_status = ttk.Label(controls, text="ожидание")
        self.lbl_status.pack(side="left")

        log_tools = ttk.Frame(frm, padding=(6, 0))
        log_tools.grid(row=1, column=0, sticky="ew")
        log_tools.columnconfigure(1, weight=1)
        ttk.Label(log_tools, text="Поиск:").grid(row=0, column=0, padx=(0, 4), pady=(6, 0))
        self.var_filter = tk.StringVar()
        ent_filter = ttk.Entry(log_tools, textvariable=self.var_filter)
        ent_filter.grid(row=0, column=1, sticky="ew", pady=(6, 0))
        ttk.Button(log_tools, text="Найти", command=self._find_in_logs).grid(row=0, column=2, padx=4, pady=(6, 0))
        ttk.Button(log_tools, text="ERROR", command=lambda: self._jump_to_level("ERROR")).grid(row=0, column=3, padx=2, pady=(6, 0))
        ttk.Button(log_tools, text="WARNING", command=lambda: self._jump_to_level("WARNING")).grid(row=0, column=4, padx=2, pady=(6, 0))
        ttk.Button(log_tools, text="INFO", command=lambda: self._jump_to_level("INFO")).grid(row=0, column=5, padx=2, pady=(6, 0))
        ttk.Button(log_tools, text="Сброс", command=self._reset_search).grid(row=0, column=6, padx=4, pady=(6, 0))

        self.txt_logs = tk.Text(frm, wrap="none", state="disabled")
        self.txt_logs.grid(row=2, column=0, sticky="nsew", padx=6, pady=6)
        self.txt_logs.tag_configure("stderr", foreground="#B00020")
        self.txt_logs.tag_configure("stdout", foreground="#222")
        self.txt_logs.tag_configure("meta", foreground="#555")
        self.txt_logs.tag_configure("search_highlight", background="#fff2a8")

        scroll_y = ttk.Scrollbar(frm, orient="vertical", command=self.txt_logs.yview)
        scroll_y.grid(row=2, column=1, sticky="ns")
        self.txt_logs.configure(yscrollcommand=scroll_y.set)

        self.status_sys = ttk.Label(frm, text="CPU: —  MEM: —  NET: —/—", foreground="#555")
        self.status_sys.grid(row=3, column=0, sticky="w", padx=8)

        tips = ttk.Label(frm, text="Подсказка: если нет start.sh/start.bat — запускается python main.py.", foreground="#555")
        tips.grid(row=4, column=0, sticky="w", padx=8)

    def _get_repeat_minutes(self) -> int:
        try:
            minutes = int(self.repeat_minutes.get())
        except (tk.TclError, ValueError):
            minutes = 1
        if minutes < 1:
            minutes = 1
        self.repeat_minutes.set(minutes)
        return minutes

    def _cancel_repeat_job(self) -> None:
        if self.repeat_job_id is not None:
            try:
                self.after_cancel(self.repeat_job_id)
            except Exception:
                pass
            finally:
                self.repeat_job_id = None

    def _schedule_repeat(self) -> None:
        if not self.repeat_enabled.get():
            self._cancel_repeat_job()
            return
        minutes = self._get_repeat_minutes()
        delay_ms = minutes * 60_000
        self._cancel_repeat_job()
        self.repeat_job_id = self.after(delay_ms, self._start_bot)
        next_time = datetime.now() + timedelta(minutes=minutes)
        self._log_meta(
            f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Следующий запуск запланирован на {next_time:%H:%M:%S}\n"
        )

    def _on_repeat_toggle(self) -> None:
        if hasattr(self, "spin_repeat"):
            state = "normal" if self.repeat_enabled.get() else "disabled"
            self.spin_repeat.configure(state=state)
        if not self.repeat_enabled.get():
            self._cancel_repeat_job()

    # ---- Tab EDIT ----
    def _build_tab_edit(self):
        frm = self.tab_edit
        frm.columnconfigure(1, weight=1)
        row = 0
        ttk.Label(frm, text="Редактируемые файлы (если есть в репозитории):").grid(row=row, column=0, sticky="w", padx=6, pady=(8,4))
        row += 1
        self.edit_files = [
            "sources_nn.yaml",
            "moderation.yaml",
            "tag_rules.yaml",
        ]
        for name in self.edit_files:
            line = ttk.Frame(frm)
            line.grid(row=row, column=0, sticky="w", padx=6, pady=4)
            ttk.Button(line, text=f"Открыть {name}", command=lambda n=name: self._open_yaml(n)).pack(side="left")
            ttk.Button(line, text="Проверить схему", command=lambda n=name: self._validate_yaml(n)).pack(side="left", padx=6)
            row += 1

    # ---- Tab UPDATE ----
    def _build_tab_update(self):
        frm = self.tab_update
        frm.columnconfigure(1, weight=1)
        row = 0

        ttk.Label(frm, text="URL репозитория GitHub (формат https://github.com/<owner>/<repo>):").grid(row=row, column=0, sticky="w", padx=6, pady=(10,4)); row += 1
        self.var_repo_url = tk.StringVar(value=self.cfg.get("repo_url", ""))
        ent_url = ttk.Entry(frm, textvariable=self.var_repo_url)
        ent_url.grid(row=row, column=0, columnspan=2, sticky="ew", padx=6); row += 1

        ttk.Label(frm, text="Ветка (branch):").grid(row=row, column=0, sticky="w", padx=6, pady=(6,4))
        self.var_branch = tk.StringVar(value=self.cfg.get("branch", "main"))
        cb_branch = ttk.Combobox(frm, textvariable=self.var_branch, values=["main", "master"], state="readonly")
        cb_branch.grid(row=row, column=1, sticky="w", padx=6); row += 1

        btns = ttk.Frame(frm)
        btns.grid(row=row, column=0, columnspan=2, sticky="w", padx=6, pady=8); row += 1
        ttk.Button(btns, text="Определить из .git/config", command=self._detect_remote_from_git).pack(side="left", padx=4)
        ttk.Button(btns, text="Проверить наличие Git", command=self._check_git).pack(side="left", padx=4)
        ttk.Button(btns, text="Обновить (git pull)", command=self._git_pull).pack(side="left", padx=4)
        ttk.Button(btns, text="Скачать ZIP и обновить", command=self._download_zip_and_update).pack(side="left", padx=4)
        ttk.Button(btns, text="Сохранить настройки", command=self._save_cfg).pack(side="left", padx=12)

        ttk.Label(frm, text="Примечание: если папка не является git-репозиторием или git недоступен, воспользуйтесь «Скачать ZIP и обновить».", foreground="#555").grid(row=row, column=0, columnspan=2, sticky="w", padx=6, pady=(0,8))

    # ---------- Helpers ----------
    def _choose_repo(self):
        path = filedialog.askdirectory(title="Выберите папку репозитория WebWork")
        if not path:
            return
        self.repo_dir = Path(path)
        self.repo_dir_var.set(str(self.repo_dir))
        self._refresh_profiles()

    def _open_repo(self):
        if not self._ensure_repo():
            return
        p = str(self.repo_dir)
        try:
            if sys.platform == "win32":
                os.startfile(p)  # type: ignore
            elif sys.platform == "darwin":
                subprocess.Popen(["open", p])
            else:
                subprocess.Popen(["xdg-open", p])
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Не удалось открыть: {e}")

    def _env_path(self, example=False) -> Path:
        if not self._ensure_repo():
            raise RuntimeError("Репозиторий не выбран")
        return self.repo_dir / (".env.example" if example else ".env")

    def _load_env(self, example=False):
        try:
            env = load_env_file(self._env_path(example=example))
        except RuntimeError as e:
            messagebox.showerror(APP_NAME, str(e)); return
        self._apply_env_to_fields(env)
        self.active_profile = None
        self.var_profile.set("")
        self._refresh_profiles()
        messagebox.showinfo(APP_NAME, ("Загружено из .env.example" if example else "Загружено из .env"))

    def _save_env(self):
        if not self._ensure_repo():
            return
        try:
            values = self._gather_env_values()
            self._write_env_to_path(self._env_path(example=False), values)
            self.env = merge_with_defaults(values)
            messagebox.showinfo(APP_NAME, f".env сохранён в {self._env_path(example=False)}")
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Ошибка сохранения .env: {e}")

    def _load_profile(self):
        if not self._ensure_repo():
            return
        name = (self.var_profile.get() or "").strip()
        if not name:
            messagebox.showwarning(APP_NAME, "Выберите профиль для загрузки")
            return
        path = self._profile_path(name)
        if not path.exists():
            messagebox.showerror(APP_NAME, f"Профиль '{name}' не найден")
            return
        try:
            env = load_env_file(path)
            self._apply_env_to_fields(env)
            self._write_env_to_path(self._env_path(False), self._gather_env_values())
            self.active_profile = name
            messagebox.showinfo(APP_NAME, f"Профиль '{name}' загружен")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Ошибка загрузки профиля: {exc}")
        self._refresh_profiles()

    def _save_profile(self):
        if not self._ensure_repo():
            return
        name = (self.var_profile.get() or self.active_profile or "").strip()
        if not name:
            messagebox.showwarning(APP_NAME, "Укажите имя профиля в выпадающем списке")
            return
        sanitized = self._sanitize_profile_name(name)
        if not sanitized:
            messagebox.showerror(APP_NAME, "Имя профиля не должно быть пустым")
            return
        try:
            values = self._gather_env_values()
            self._write_env_to_path(self._profile_path(sanitized, ensure_dir=True), values)
            self._write_env_to_path(self._env_path(False), values)
            self.env = merge_with_defaults(values)
            self.active_profile = sanitized
            self.var_profile.set(sanitized)
            messagebox.showinfo(APP_NAME, f"Профиль '{sanitized}' сохранён")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Ошибка сохранения профиля: {exc}")
        self._refresh_profiles()

    def _new_profile(self):
        if not self._ensure_repo():
            return
        name = simpledialog.askstring(APP_NAME, "Название нового профиля")
        if not name:
            return
        sanitized = self._sanitize_profile_name(name)
        if not sanitized:
            messagebox.showerror(APP_NAME, "Имя профиля не должно быть пустым")
            return
        path = self._profile_path(sanitized, ensure_dir=True)
        if path.exists():
            messagebox.showerror(APP_NAME, "Профиль с таким именем уже существует")
            return
        try:
            values = self._gather_env_values()
            self._write_env_to_path(path, values)
            self._write_env_to_path(self._env_path(False), values)
            self.env = merge_with_defaults(values)
            self.active_profile = sanitized
            self.var_profile.set(sanitized)
            messagebox.showinfo(APP_NAME, f"Создан профиль '{sanitized}'")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Ошибка создания профиля: {exc}")
        self._refresh_profiles()

    def _duplicate_profile(self):
        if not self._ensure_repo():
            return
        source = (self.var_profile.get() or "").strip()
        if not source:
            messagebox.showwarning(APP_NAME, "Выберите профиль для дублирования")
            return
        src_path = self._profile_path(source)
        if not src_path.exists():
            messagebox.showerror(APP_NAME, f"Профиль '{source}' не найден")
            return
        name = simpledialog.askstring(APP_NAME, "Название нового профиля")
        if not name:
            return
        sanitized = self._sanitize_profile_name(name)
        if not sanitized:
            messagebox.showerror(APP_NAME, "Имя профиля не должно быть пустым")
            return
        dst_path = self._profile_path(sanitized, ensure_dir=True)
        if dst_path.exists():
            messagebox.showerror(APP_NAME, "Профиль с таким именем уже существует")
            return
        try:
            values = load_env_file(src_path)
            self._write_env_to_path(dst_path, values)
            self._apply_env_to_fields(values)
            self._write_env_to_path(self._env_path(False), self._gather_env_values())
            self.active_profile = sanitized
            self.var_profile.set(sanitized)
            messagebox.showinfo(APP_NAME, f"Профиль '{source}' скопирован в '{sanitized}'")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Ошибка дублирования профиля: {exc}")
        self._refresh_profiles()

    def _validate_env(self):
        try:
            import jsonschema
        except Exception:
            messagebox.showerror(APP_NAME, "Установите пакет jsonschema для проверки .env")
            return

        values = self._gather_env_values()
        typed: dict[str, object] = {}
        errors: list[str] = []

        mode = self.fields["TELEGRAM_MODE"].get().strip() or "BOT_API"
        typed["TELEGRAM_MODE"] = mode

        for key, value in values.items():
            if key == "TELEGRAM_MODE":
                continue
            if key in ENV_BOOL_KEYS:
                low = value.lower()
                if low in {"true", "1", "yes"}:
                    typed[key] = True
                elif low in {"false", "0", "no"}:
                    typed[key] = False
                else:
                    errors.append(f"{key}: ожидается true/false")
            elif key in ENV_INT_KEYS:
                try:
                    typed[key] = int(value)
                except ValueError:
                    errors.append(f"{key}: ожидается целое число")
            elif key in ENV_FLOAT_KEYS:
                try:
                    typed[key] = float(value)
                except ValueError:
                    errors.append(f"{key}: ожидается число")
            else:
                typed[key] = value

        # Дополнительные поля, которые могли быть в профиле, но отсутствуют в форме
        for key in ("TG_API_HASH", "TG_API_ID", "TELETHON_API_ID", "TELETHON_API_HASH"):
            if key in values and key not in typed:
                typed[key] = values[key]

        if errors:
            messagebox.showwarning(APP_NAME, "Исправьте ошибки: " + "; ".join(errors))
            return

        try:
            jsonschema.validate(typed, ENV_SCHEMA)
        except jsonschema.ValidationError as exc:
            messagebox.showerror(APP_NAME, f"Неверное окружение: {exc.message}")
            return

        messagebox.showinfo(APP_NAME, "Файл .env проходит проверку схемы")

    def _open_yaml(self, name: str):
        if not self._ensure_repo():
            return
        p = self.repo_dir / name
        TextEditor(self, p)

    def _validate_yaml(self, name: str):
        if not self._ensure_repo():
            return
        path = self.repo_dir / name
        if not path.exists():
            messagebox.showerror(APP_NAME, f"Файл {name} не найден в репозитории")
            return
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Ошибка чтения YAML: {exc}")
            return
        schema = YAML_SCHEMAS.get(name)
        if not schema:
            messagebox.showinfo(APP_NAME, f"Схема для {name} не задана, синтаксис корректен")
            return
        try:
            import jsonschema
        except Exception:
            messagebox.showerror(APP_NAME, "Установите пакет jsonschema для проверки YAML")
            return
        try:
            jsonschema.validate(data, schema, format_checker=jsonschema.FormatChecker())
        except jsonschema.ValidationError as exc:
            path_hint = " → ".join(str(p) for p in exc.absolute_path)
            messagebox.showerror(
                APP_NAME,
                f"{name}: несоответствие схеме: {exc.message}" + (f" (путь: {path_hint})" if path_hint else ""),
            )
        else:
            messagebox.showinfo(APP_NAME, f"{name}: проверка схемы успешно пройдена")

    def _ensure_repo(self) -> bool:
        if self.repo_dir and (self.repo_dir / "main.py").exists():
            return True
        txt = self.repo_dir_var.get().strip()
        if txt:
            p = Path(txt)
            if (p / "main.py").exists():
                self.repo_dir = p
                self._refresh_profiles()
                return True
        messagebox.showwarning(APP_NAME, "Укажите папку, где лежит main.py (репозиторий WebWork).")
        return False

    def _collect_env(self) -> dict:
        env = os.environ.copy()
        for k, var in self.fields.items():
            v = var.get().strip()
            if v != "":
                env[k] = v
        # зеркалим TELETHON_* если TG_* указаны
        if "TG_API_ID" in env and env["TG_API_ID"] and not env.get("TELETHON_API_ID"):
            env["TELETHON_API_ID"] = env["TG_API_ID"]
        if "TG_API_HASH" in env and env["TG_API_HASH"] and not env.get("TELETHON_API_HASH"):
            env["TELETHON_API_HASH"] = env["TG_API_HASH"]
        return env

    # ---------- RUN actions ----------
    def _start_bot(self):
        if self.runner.proc and self.runner.proc.poll() is None:
            messagebox.showwarning(APP_NAME, "Процесс уже выполняется")
            return
        self._cancel_repeat_job()
        self._start_with_args([])

    def _start_with_args(self, extra_args: list[str]):
        if not self._ensure_repo():
            return
        if sys.platform == "win32" and (self.repo_dir / "start.bat").exists():
            cmd_list = [str(self.repo_dir / "start.bat")]
        elif sys.platform != "win32" and (self.repo_dir / "start.sh").exists():
            cmd_list = ["bash", str(self.repo_dir / "start.sh")]
        else:
            cmd_list = [sys.executable, "main.py"]
        cmd_list = [*cmd_list, *extra_args]
        env = self._collect_env()
        try:
            self.runner.start(cmd_list, cwd=str(self.repo_dir), env=env)
            self._log_meta(
                f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Запуск: "
                f"{' '.join(shlex.quote(x) for x in cmd_list)}\n"
            )
        except RuntimeError as e:
            messagebox.showerror(APP_NAME, str(e))

    def _stop_bot(self):
        if self.repeat_enabled.get():
            self.repeat_enabled.set(False)
            self._on_repeat_toggle()
        self.runner.terminate()
        self._log_meta(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Остановка процесса по запросу пользователя\n")

    def _create_venv(self):
        if not self._ensure_repo():
            return
        if (self.repo_dir / ".venv").exists():
            if not messagebox.askyesno(APP_NAME, ".venv уже существует. Пересоздать?"):
                return
        cmd_list = [sys.executable, "-m", "venv", ".venv"]
        try:
            self.runner.start(cmd_list, cwd=str(self.repo_dir), env=os.environ.copy())
            self._log_meta(
                "Создание виртуального окружения (.venv). "
                "Для PowerShell может потребоваться Set-ExecutionPolicy RemoteSigned.\n"
            )
        except RuntimeError as e:
            messagebox.showerror(APP_NAME, str(e))

    def _install_telethon(self):
        """pip install --upgrade telethon (и pip) в текущем интерпретаторе."""
        cmd_list = [sys.executable, "-m", "pip", "install", "--upgrade", "pip", "telethon"]
        try:
            self.runner.start(cmd_list, cwd=str(self.repo_dir) if self.repo_dir else None, env=os.environ.copy())
            self._log_meta(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Установка Telethon: {' '.join(shlex.quote(x) for x in cmd_list)}\n")
        except RuntimeError as e:
            messagebox.showerror(APP_NAME, str(e))

    def _install_requirements(self):
        """pip install -r requirements.txt (если есть)."""
        if not self._ensure_repo():
            return
        req = self.repo_dir / "requirements.txt"
        if not req.exists():
            messagebox.showwarning(APP_NAME, "Файл requirements.txt не найден в репозитории.")
            return
        cmd_list = [sys.executable, "-m", "pip", "install", "-r", str(req)]
        try:
            self.runner.start(cmd_list, cwd=str(self.repo_dir), env=os.environ.copy())
            self._log_meta(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Установка зависимостей из requirements.txt\n")
        except RuntimeError as e:
            messagebox.showerror(APP_NAME, str(e))

    def _check_getme(self):
        token = (self.fields.get("TELEGRAM_BOT_TOKEN") or tk.StringVar()).get().strip()
        if not token:
            messagebox.showwarning(APP_NAME, "Укажите TELEGRAM_BOT_TOKEN в профиле")
            return
        url = f"https://api.telegram.org/bot{token}/getMe"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Ошибка getMe: {exc}")
            return
        if data.get("ok"):
            result = data.get("result", {})
            username = result.get("username") or "—"
            bot_id = result.get("id")
            messagebox.showinfo(APP_NAME, f"Токен валиден: @{username} (id={bot_id})")
        else:
            messagebox.showerror(APP_NAME, f"getMe вернул ошибку: {data}")

    def _check_telethon_login(self):
        if not self._ensure_repo():
            return
        env = self._collect_env()
        api_id = env.get("TG_API_ID") or env.get("TELETHON_API_ID")
        api_hash = env.get("TG_API_HASH") or env.get("TELETHON_API_HASH")
        if not api_id or not api_hash:
            messagebox.showwarning(APP_NAME, "Укажите TG_API_ID/TG_API_HASH или TELETHON_API_ID/TELETHON_API_HASH")
            return
        code = (
            "from telethon.sync import TelegramClient\n"
            "import os\n"
            "api_id=os.getenv('TG_API_ID') or os.getenv('TELETHON_API_ID')\n"
            "api_hash=os.getenv('TG_API_HASH') or os.getenv('TELETHON_API_HASH')\n"
            "sess=os.getenv('TG_SESSION_FILE') or 'webwork'\n"
            "with TelegramClient(sess, int(api_id), api_hash) as client:\n"
            "    me = client.get_me()\n"
            "    print('OK', me.username or me.id)\n"
        )
        try:
            self.runner.start(
                [sys.executable, "-c", code],
                cwd=str(self.repo_dir),
                env=env,
            )
            self._log_meta("Проверка Telethon: client.get_me()\n")
        except RuntimeError as e:
            messagebox.showerror(APP_NAME, str(e))

    def _network_test(self):
        if not self._ensure_repo():
            return

        def run_checks():
            results: list[str] = ["=== Сетевой тест ==="]

            def check_url(url: str, method: str = "GET") -> None:
                start = time.perf_counter()
                req = urllib.request.Request(url)
                if method.upper() == "HEAD":
                    req.get_method = lambda: "HEAD"  # type: ignore[attr-defined]
                try:
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        resp.read(1 if method == "GET" else 0)
                        status = resp.status
                except Exception as exc:
                    results.append(f"{method} {url} → ошибка: {exc}")
                    return
                elapsed = (time.perf_counter() - start) * 1000
                results.append(f"{method} {url} → {status}, {elapsed:.0f} мс")

            check_url("https://api.telegram.org", method="GET")

            sample_urls = []
            sources_file = self.repo_dir / "sources_nn.yaml"
            if sources_file.exists():
                try:
                    raw = yaml.safe_load(sources_file.read_text(encoding="utf-8")) or {}
                    for entry in raw.get("sources", [])[:2]:
                        if isinstance(entry, dict) and entry.get("url"):
                            sample_urls.append(str(entry["url"]))
                except Exception as exc:
                    results.append(f"Ошибка чтения sources_nn.yaml: {exc}")

            for url in sample_urls:
                check_url(url, method="HEAD")

            text = "\n".join(results) + "\n"
            self.after(0, lambda: self._log_meta(text))

        threading.Thread(target=run_checks, daemon=True).start()

    def _env_check(self):
        """Диагностика окружения: python, pip, telethon, git, repo."""
        lines = []
        lines.append("=== Проверка окружения ===")
        lines.append(f"Python: {sys.version} ({sys.executable})")
        # pip version
        try:
            out = subprocess.check_output([sys.executable, "-m", "pip", "--version"], text=True, stderr=subprocess.STDOUT)
            lines.append("pip: " + out.strip())
        except Exception as e:
            lines.append(f"pip: ошибка: {e}")
        # telethon
        try:
            out = subprocess.check_output([sys.executable, "-c", "import telethon, sys; print('Telethon', telethon.__version__, '->', sys.executable)"], text=True, stderr=subprocess.STDOUT)
            lines.append(out.strip())
        except subprocess.CalledProcessError as e:
            lines.append("Telethon: не установлен (или ошибка импорта)")
            lines.append(e.output.strip())
        except Exception as e:
            lines.append(f"Telethon: ошибка: {e}")
        # git
        git_path = shutil.which("git")
        lines.append("git: " + (git_path or "не найден в PATH"))
        if self.repo_dir:
            lines.append(f"repo_dir: {self.repo_dir}")
            lines.append(".git: " + ("есть" if (self.repo_dir / ".git").exists() else "нет"))
        self._set_logs("\n".join(lines) + "\n")

    # ---------- UPDATE actions ----------
    def _load_cfg(self):
        if CFG_FILE.exists():
            try:
                return json.loads(CFG_FILE.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_cfg(self):
        data = {
            "repo_url": self.var_repo_url.get().strip(),
            "branch": self.var_branch.get().strip() or "main",
        }
        try:
            CFG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            messagebox.showinfo(APP_NAME, f"Сохранено: {CFG_FILE}")
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Ошибка сохранения настроек: {e}")

    def _detect_remote_from_git(self):
        """Читает .git/config и заполняет URL/ветку (если возможно)."""
        if not self._ensure_repo():
            return
        git_cfg = self.repo_dir / ".git" / "config"
        if not git_cfg.exists():
            messagebox.showwarning(APP_NAME, "Это не git-репозиторий (нет .git).")
            return
        try:
            cfg = git_cfg.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r'\[remote "origin"\][^\[]*?url\s*=\s*(.+)', cfg, re.MULTILINE)
            if m:
                url = m.group(1).strip()
                self.var_repo_url.set(url)
            # ветка по умолчанию
            head = (self.repo_dir / ".git" / "HEAD").read_text(encoding="utf-8", errors="ignore")
            m2 = re.search(r"ref:\s+refs/heads/([^\s]+)", head)
            if m2:
                self.var_branch.set(m2.group(1))
            messagebox.showinfo(APP_NAME, "Данные origin считаны из .git/config.")
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Не удалось прочитать .git/config: {e}")

    def _check_git(self):
        path = shutil.which("git")
        if path:
            messagebox.showinfo(APP_NAME, f"git найден: {path}")
        else:
            messagebox.showwarning(APP_NAME, "git не найден в PATH. Установите Git или используйте способ «Скачать ZIP».")

    def _git_pull(self):
        if not self._ensure_repo():
            return
        if not (self.repo_dir / ".git").exists():
            messagebox.showwarning(APP_NAME, "Текущая папка не является git-репозиторием.")
            return
        if not shutil.which("git"):
            messagebox.showwarning(APP_NAME, "git не найден в PATH.")
            return
        # безопасная последовательность: fetch + pull (ff-only)
        cmd_list = ["git", "-C", str(self.repo_dir), "pull", "--ff-only"]
        try:
            self.runner.start(cmd_list, cwd=str(self.repo_dir), env=os.environ.copy())
            self._log_meta(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] git pull\n")
        except RuntimeError as e:
            messagebox.showerror(APP_NAME, str(e))

    def _download_zip_and_update(self):
        """Скачивает ZIP с GitHub и обновляет файлы в repo_dir. Подходит когда нет git/репо не клонирован."""
        if not self._ensure_repo():
            return
        url = self.var_repo_url.get().strip()
        branch = self.var_branch.get().strip() or "main"
        if not url:
            messagebox.showwarning(APP_NAME, "Укажите URL репозитория GitHub (https://github.com/<owner>/<repo>).")
            return
        # нормализуем: если это страница, берём codeload zip
        # Принимаем форматы:
        # - https://github.com/owner/repo
        # - https://github.com/owner/repo.git
        m = re.match(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", url, re.IGNORECASE)
        if not m:
            messagebox.showwarning(APP_NAME, "URL должен быть вида https://github.com/<owner>/<repo>")
            return
        owner, repo = m.group(1), m.group(2)
        zip_url = f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{branch}"

        # Скачиваем ZIP во временный файл
        try:
            self._log_meta(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Скачивание ZIP: {zip_url}\n")
            with urllib.request.urlopen(zip_url) as resp:
                data = resp.read()
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Не удалось скачать ZIP: {e}")
            return

        # Распаковка во временную директорию
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                zpath = Path(tmpdir) / "repo.zip"
                zpath.write_bytes(data)
                with zipfile.ZipFile(zpath, "r") as zf:
                    zf.extractall(tmpdir)
                # Внутри архива папка вида repo-<branch>
                root = None
                for p in Path(tmpdir).iterdir():
                    if p.is_dir() and p.name.lower().startswith(repo.lower().replace(".git", "")):
                        root = p; break
                if not root:
                    raise RuntimeError("Не удалось найти корневую папку в архиве.")
                # Бэкап текущей папки (кроме .venv и .git), zip-архив в /backup_YYYYmmddHHMMSS.zip
                ts = datetime.now().strftime("%Y%m%d%H%M%S")
                backup_name = self.repo_dir.parent / f"{self.repo_dir.name}_backup_{ts}"
                shutil.make_archive(str(backup_name), "zip", root_dir=str(self.repo_dir), logger=None)
                # Копирование файлов поверх (кроме .git, .venv, backup_*)
                self._copy_tree_overwrite(src=root, dst=self.repo_dir, exclude={".git", ".venv"})
                messagebox.showinfo(APP_NAME, f"Обновление завершено. Создан бэкап: {backup_name}.zip")
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Ошибка распаковки/обновления: {e}")

    def _copy_tree_overwrite(self, src: Path, dst: Path, exclude=set()):
        for root, dirs, files in os.walk(src):
            rel = Path(root).relative_to(src)
            # фильтруем исключения
            dirs[:] = [d for d in dirs if d not in exclude and not d.startswith("backup_")]
            target_dir = dst / rel
            target_dir.mkdir(parents=True, exist_ok=True)
            for f in files:
                if f in exclude or f.startswith("backup_"):
                    continue
                s = Path(root) / f
                d = target_dir / f
                # стараемся не затирать .git и .venv
                if ".git" in d.parts or ".venv" in d.parts:
                    continue
                shutil.copy2(s, d)

    # ---------- Runner callbacks ----------
    def on_output(self, items):
        self.txt_logs.configure(state="normal")
        for kind, line in items:
            tag = "stderr" if kind == "stderr" else "stdout"
            self.txt_logs.insert("end", line, tag)
        self.txt_logs.see("end")
        self.txt_logs.configure(state="disabled")

    def on_state_change(self, state: str, code: int | None = None):
        if state == "running":
            self.lbl_status.configure(text="выполняется")
            self._net_io_start = None
        elif state == "stopped":
            self.lbl_status.configure(text=f"завершено (код {code})")
            self._net_io_start = None
            if hasattr(self, "status_sys"):
                self.status_sys.configure(text="CPU: —  MEM: —  NET: —/—")
            self._schedule_repeat()

    def _find_in_logs(self, pattern: str | None = None):
        pattern = (pattern or self.var_filter.get()).strip()
        if not pattern:
            messagebox.showinfo(APP_NAME, "Введите текст для поиска")
            return
        start = self._last_search_pos or "1.0"
        self.txt_logs.configure(state="normal")
        idx = self.txt_logs.search(pattern, start, tk.END, nocase=True)
        if not idx and start != "1.0":
            idx = self.txt_logs.search(pattern, "1.0", tk.END, nocase=True)
        if idx:
            end = f"{idx}+{len(pattern)}c"
            self.txt_logs.tag_remove("search_highlight", "1.0", tk.END)
            self.txt_logs.tag_add("search_highlight", idx, end)
            self.txt_logs.see(idx)
            self._last_search_pos = end
        else:
            self.txt_logs.tag_remove("search_highlight", "1.0", tk.END)
            self._last_search_pos = "1.0"
            messagebox.showinfo(APP_NAME, f"'{pattern}' не найдено в логах")
        self.txt_logs.configure(state="disabled")

    def _jump_to_level(self, level: str):
        self.var_filter.set(level)
        self._last_search_pos = "1.0"
        self._find_in_logs(level)

    def _reset_search(self):
        self.var_filter.set("")
        self._last_search_pos = "1.0"
        self.txt_logs.configure(state="normal")
        self.txt_logs.tag_remove("search_highlight", "1.0", tk.END)
        self.txt_logs.configure(state="disabled")

    def _set_logs(self, text: str):
        self.txt_logs.configure(state="normal")
        self.txt_logs.delete("1.0", "end")
        self.txt_logs.insert("end", text)
        self.txt_logs.configure(state="disabled")

    def _log_meta(self, text: str):
        self.txt_logs.configure(state="normal")
        self.txt_logs.insert("end", text, "meta")
        self.txt_logs.see("end")
        self.txt_logs.configure(state="disabled")

    def _tick(self):
        self.runner.poll()
        self._update_psutil()
        self.after(100, self._tick)

    def _update_psutil(self):
        if not hasattr(self, "status_sys"):
            return
        now = time.time()
        if now - self._psutil_last_update < 1:
            return
        self._psutil_last_update = now
        if self._psutil_failed:
            return
        proc = getattr(self.runner, "proc", None)
        if not proc or proc.poll() is not None:
            self.status_sys.configure(text="CPU: 0.0%  MEM: —  NET: —/—")
            self._net_io_start = None
            return
        try:
            import psutil  # type: ignore
        except Exception:
            self._psutil_failed = True
            self.status_sys.configure(text="psutil недоступен — установите пакет psutil")
            return
        try:
            proc_info = psutil.Process(proc.pid)
            cpu = proc_info.cpu_percent(interval=0.0)
            mem = proc_info.memory_info().rss / (1024 * 1024)
            net_text = "—/—"
            try:
                net = proc_info.net_io_counters()  # type: ignore[attr-defined]
            except Exception:
                net = None
            if net:
                if self._net_io_start is None:
                    self._net_io_start = (net.bytes_sent, net.bytes_recv)
                sent = max(0.0, (net.bytes_sent - self._net_io_start[0]) / 1024)
                recv = max(0.0, (net.bytes_recv - self._net_io_start[1]) / 1024)
                net_text = f"{sent:.0f}К/{recv:.0f}К"
            self.status_sys.configure(
                text=f"CPU: {cpu:.1f}%  MEM: {mem:.1f} МБ  NET: {net_text}"
            )
        except Exception:
            self.status_sys.configure(text="CPU: —  MEM: —  NET: —/—")


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover - пользовательская среда
        _fatal_error("Критическая ошибка при запуске панели управления WebWork.", exc)

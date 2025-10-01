import os
import sys
import io
import re
import json
import shlex
import time
import queue
import shutil
import zipfile
import tempfile
import threading
import subprocess
import urllib.request
from pathlib import Path
from datetime import datetime

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_NAME = "WebWork Manager"
APP_VERSION = "3.0"
CFG_FILE = Path.home() / ".webwork_manager.json"  # хранение настроек (url, ветка и т.д.)

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

# ---------------- Основное приложение ----------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry("1180x780")
        self.minsize(1040, 680)

        self.repo_dir: Path | None = None
        self.env: dict[str, str] = {}
        self.runner = ProcessRunner(self.on_output, self.on_state_change)
        self.cfg = self._load_cfg()

        self._build_ui()
        self.after(100, self._tick)

    # ---------- UI ----------
    def _build_ui(self):
        # ВЕРХ
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Папка репозитория WebWork:").pack(side="left")
        self.repo_entry = ttk.Entry(top, width=60)
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

    # ---- Tab ENV ----
    def _build_tab_env(self):
        frm = self.tab_env
        frm.columnconfigure(1, weight=1)
        row = 0

        bbar = ttk.Frame(frm)
        bbar.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(8,6))
        ttk.Button(bbar, text="Загрузить из .env", command=self._load_env).pack(side="left", padx=4)
        ttk.Button(bbar, text="Загрузить из .env.example", command=lambda: self._load_env(example=True)).pack(side="left", padx=4)
        ttk.Button(bbar, text="Сохранить в .env", command=self._save_env).pack(side="left", padx=4)
        ttk.Button(bbar, text="Проверить заполнение", command=self._validate_env).pack(side="left", padx=4)
        row += 1

        ttk.Separator(frm).grid(row=row, column=0, columnspan=3, sticky="ew", pady=6); row += 1
        self.fields = {}

        def add_field(label, key, values=None, hint=""):
            nonlocal row
            ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=4)
            if values:
                var = tk.StringVar()
                cb = ttk.Combobox(frm, textvariable=var, values=values, state="readonly")
                cb.grid(row=row, column=1, sticky="ew", padx=6, pady=4)
                self.fields[key] = var
            else:
                var = tk.StringVar()
                ent = ttk.Entry(frm, textvariable=var)
                ent.grid(row=row, column=1, sticky="ew", padx=6, pady=4)
                self.fields[key] = var
            if hint:
                ttk.Label(frm, text=hint, foreground="#555").grid(row=row, column=2, sticky="w")
            row += 1

        # Режим
        add_field("TELEGRAM_MODE", "TELEGRAM_MODE", values=["BOT_API", "MTPROTO", "WEB"], hint="Способ отправки")

        ttk.Separator(frm).grid(row=row, column=0, columnspan=3, sticky="ew", pady=6); row += 1

        # Bot API
        ttk.Label(frm, text="Bot API", font=("", 10, "bold")).grid(row=row, column=0, sticky="w", padx=6); row += 1
        add_field("TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN", hint="Токен бота")
        add_field("CHANNEL_CHAT_ID", "CHANNEL_CHAT_ID", hint="@alias или -100...")
        add_field("REVIEW_CHAT_ID", "REVIEW_CHAT_ID", hint="для модерации/RAW")
        add_field("PARSE_MODE", "PARSE_MODE", values=["HTML", "MarkdownV2"])
        add_field("DRY_RUN", "DRY_RUN", values=["false", "true"])
        add_field("CAPTION_LIMIT", "CAPTION_LIMIT")

        ttk.Separator(frm).grid(row=row, column=0, columnspan=3, sticky="ew", pady=6); row += 1

        # MTProto
        ttk.Label(frm, text="Telegram API (MTProto)", font=("", 10, "bold")).grid(row=row, column=0, sticky="w", padx=6); row += 1
        add_field("TG_API_ID", "TG_API_ID", hint="или TELETHON_API_ID")
        add_field("TG_API_HASH", "TG_API_HASH", hint="или TELETHON_API_HASH")
        add_field("TG_SESSION_FILE", "TG_SESSION_FILE", hint="путь к .session (опц.)")
        add_field("TG_SESSION_STRING", "TG_SESSION_STRING", hint="строка-сессия (опц.)")

        ttk.Separator(frm).grid(row=row, column=0, columnspan=3, sticky="ew", pady=6); row += 1

        # Раздельные чаты
        ttk.Label(frm, text="Раздельные чаты (если используются)", font=("", 10, "bold")).grid(row=row, column=0, sticky="w", padx=6); row += 1
        add_field("CHANNEL_TEXT_CHAT_ID", "CHANNEL_TEXT_CHAT_ID", hint="@alias или -100...")
        add_field("CHANNEL_MEDIA_CHAT_ID", "CHANNEL_MEDIA_CHAT_ID", hint="@alias или -100...")

        ttk.Separator(frm).grid(row=row, column=0, columnspan=3, sticky="ew", pady=6); row += 1

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

    # ---- Tab RUN ----
    def _build_tab_run(self):
        frm = self.tab_run
        frm.rowconfigure(1, weight=1)
        frm.columnconfigure(0, weight=1)

        controls = ttk.Frame(frm, padding=(4,6))
        controls.grid(row=0, column=0, sticky="ew")
        ttk.Button(controls, text="Запустить", command=self._start_bot).pack(side="left", padx=4)
        ttk.Button(controls, text="Остановить", command=self._stop_bot).pack(side="left", padx=4)
        ttk.Button(controls, text="Очистить лог", command=lambda: self._set_logs("")).pack(side="left", padx=4)

        ttk.Separator(controls, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Button(controls, text="Установить Telethon", command=self._install_telethon).pack(side="left", padx=4)
        ttk.Button(controls, text="Проверка окружения", command=self._env_check).pack(side="left", padx=4)
        ttk.Button(controls, text="Установить requirements.txt", command=self._install_requirements).pack(side="left", padx=4)

        ttk.Label(controls, text="Статус:").pack(side="left", padx=(16,4))
        self.lbl_status = ttk.Label(controls, text="ожидание")
        self.lbl_status.pack(side="left")

        self.txt_logs = tk.Text(frm, wrap="none", state="disabled")
        self.txt_logs.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        self.txt_logs.tag_configure("stderr", foreground="#B00020")
        self.txt_logs.tag_configure("stdout", foreground="#222")
        self.txt_logs.tag_configure("meta", foreground="#555")

        scroll_y = ttk.Scrollbar(frm, orient="vertical", command=self.txt_logs.yview)
        scroll_y.grid(row=1, column=1, sticky="ns")
        self.txt_logs.configure(yscrollcommand=scroll_y.set)

        tips = ttk.Label(frm, text="Подсказка: если нет start.sh/start.bat — запускается python main.py.", foreground="#555")
        tips.grid(row=2, column=0, sticky="w", padx=8)

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
            btn = ttk.Button(frm, text=f"Открыть {name}", command=lambda n=name: self._open_yaml(n))
            btn.grid(row=row, column=0, sticky="w", padx=6, pady=4)
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
        self.repo_entry.delete(0, "end")
        self.repo_entry.insert(0, str(self.repo_dir))

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
        merged = merge_with_defaults(env)
        self.env = merged
        for k, var in self.fields.items():
            var.set(self.env.get(k, ""))
        messagebox.showinfo(APP_NAME, ("Загружено из .env.example" if example else "Загружено из .env"))

    def _save_env(self):
        if not self._ensure_repo():
            return
        for k, var in self.fields.items():
            self.env[k] = var.get().strip()
        cleaned = {k: v for k, v in self.env.items() if v is not None and str(v) != ""}
        try:
            self._env_path(example=False).write_text(dump_env(cleaned), encoding="utf-8")
            messagebox.showinfo(APP_NAME, f".env сохранён в {self._env_path(example=False)}")
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Ошибка сохранения .env: {e}")

    def _validate_env(self):
        missing = []
        mode = self.fields["TELEGRAM_MODE"].get().strip() or "BOT_API"
        if mode.upper() == "BOT_API":
            for k in ("TELEGRAM_BOT_TOKEN", "CHANNEL_CHAT_ID"):
                if not self.fields[k].get().strip():
                    missing.append(k)
        elif mode.upper() == "MTPROTO":
            # допускаем два имени переменных
            id_ok = self.fields["TG_API_ID"].get().strip() or self.env.get("TELETHON_API_ID", "")
            hash_ok = self.fields["TG_API_HASH"].get().strip() or self.env.get("TELETHON_API_HASH", "")
            if not id_ok: missing.append("TG_API_ID/TELETHON_API_ID")
            if not hash_ok: missing.append("TG_API_HASH/TELETHON_API_HASH")
        if missing:
            messagebox.showwarning(APP_NAME, "Заполните обязательные поля: " + ", ".join(missing))
        else:
            messagebox.showinfo(APP_NAME, "Похоже, всё заполнено нормально 🙂")

    def _open_yaml(self, name: str):
        if not self._ensure_repo():
            return
        p = self.repo_dir / name
        TextEditor(self, p)

    def _ensure_repo(self) -> bool:
        if self.repo_dir and (self.repo_dir / "main.py").exists():
            return True
        txt = self.repo_entry.get().strip()
        if txt:
            p = Path(txt)
            if (p / "main.py").exists():
                self.repo_dir = p
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
        if not self._ensure_repo():
            return
        if sys.platform == "win32" and (self.repo_dir / "start.bat").exists():
            cmd_list = [str(self.repo_dir / "start.bat")]
        elif sys.platform != "win32" and (self.repo_dir / "start.sh").exists():
            cmd_list = ["bash", str(self.repo_dir / "start.sh")]
        else:
            cmd_list = [sys.executable, "main.py"]
        env = self._collect_env()
        try:
            self.runner.start(cmd_list, cwd=str(self.repo_dir), env=env)
            self._log_meta(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Запуск: {' '.join(shlex.quote(x) for x in cmd_list)}\n")
        except RuntimeError as e:
            messagebox.showerror(APP_NAME, str(e))

    def _stop_bot(self):
        self.runner.terminate()
        self._log_meta(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Остановка процесса по запросу пользователя\n")

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
        elif state == "stopped":
            self.lbl_status.configure(text=f"завершено (код {code})")

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
        self.after(100, self._tick)


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()

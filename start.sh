#!/usr/bin/env bash
set -e

# create and activate virtual environment
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
. .venv/bin/activate

ensure_pip() {
  if python -m pip --version >/dev/null 2>&1; then
    return 0
  fi

  python -m ensurepip --upgrade >/dev/null 2>&1 || true

  if python -m pip --version >/dev/null 2>&1; then
    return 0
  fi

  tmp_file="$(mktemp)"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "https://bootstrap.pypa.io/get-pip.py" -o "$tmp_file"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$tmp_file" "https://bootstrap.pypa.io/get-pip.py"
  else
    echo "Neither curl nor wget is available to download get-pip.py" >&2
    rm -f "$tmp_file"
    return 1
  fi

  if [ ! -s "$tmp_file" ]; then
    echo "Failed to download get-pip.py" >&2
    rm -f "$tmp_file"
    return 1
  fi

  python "$tmp_file"
  rm -f "$tmp_file"
}

ensure_pip

# install dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# initialize configuration if missing
if [ ! -f "$HOME/NewsBot/.env" ] && [ -f ".env.example" ]; then
  python -m config init || cp .env.example "$HOME/NewsBot/.env"
fi

# run the bot with any passed arguments
python main.py "$@"

cat <<'EOT'

Запуск завершён.
Дальнейшие команды:
  python main.py             # запуск одного прохода
  python main.py --loop      # запуск в бесконечном цикле
EOT

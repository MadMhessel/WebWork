#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PY_BIN="${PYTHON:-python3}"
if [ ! -d ".venv" ]; then
  "$PY_BIN" -m venv .venv
fi
# shellcheck source=/dev/null
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if [ ! -f "$HOME/NewsBot/.env" ] && [ -f ".env.example" ]; then
  python -m config init || cp .env.example "$HOME/NewsBot/.env"
fi

echo "[INFO] WebWork loop запускается. Для остановки нажмите Ctrl+C."
while true; do
  if python -m webwork --loop "$@"; then
    exit_code=0
    echo "[INFO] WebWork завершил цикл. Перезапуск через 10 секунд..."
  else
    exit_code=$?
    echo "[WARN] WebWork завершился с кодом $exit_code. Перезапуск через 10 секунд..." >&2
  fi
  sleep 10
done

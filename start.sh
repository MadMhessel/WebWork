#!/usr/bin/env bash
set -e

# create and activate virtual environment
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
. .venv/bin/activate

# install dependencies
pip install --upgrade pip
pip install -r requirements.txt

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

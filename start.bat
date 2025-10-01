@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
call ".venv\Scripts\python.exe" -X utf8 -m pip install -r requirements.txt --no-cache-dir
call ".venv\Scripts\python.exe" -X utf8 main.py %*
endlocal

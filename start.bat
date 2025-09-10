@echo off
setlocal

rem create and activate virtual environment
if not exist ".venv" (
    python -m venv .venv
)
call .venv\Scripts\activate

rem install dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

rem initialize configuration if missing
set "ENV_PATH=%USERPROFILE%\NewsBot\.env"
if not exist "%ENV_PATH%" (
    if not exist "%USERPROFILE%\NewsBot" mkdir "%USERPROFILE%\NewsBot"
    if exist ".env.example" (
        python -m config init || copy ".env.example" "%ENV_PATH%"
    )
)

rem run the bot with any passed arguments
python main.py %*

echo.
echo Запуск завершён.
echo Дальнейшие команды:
echo   python main.py             # запуск одного прохода
echo   python main.py --loop      # запуск в бесконечном цикле

pause

endlocal

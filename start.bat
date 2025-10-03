@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

rem Ensure we run from the repository root
pushd "%~dp0" >nul 2>&1

set "PY_CMD="
set "PY_ARGS="
where /Q py.exe 2>nul
if not errorlevel 1 (
    set "PY_CMD=py"
    set "PY_ARGS=-3"
    goto :after_python_detect
)
for %%C in (python3 python) do (
    where /Q %%C.exe 2>nul
    if not errorlevel 1 (
        set "PY_CMD=%%C"
        set "PY_ARGS="
        goto :after_python_detect
    )
)
echo [ERROR] Python 3.x is not available in PATH. Install it from https://www.python.org/downloads/ and try again.
set "ERR=9009"
popd >nul 2>&1
endlocal & exit /b %ERR%

:after_python_detect
set "VENV_DIR=%CD%\.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [INFO] Creating virtual environment in "%VENV_DIR%"
    call %PY_CMD% %PY_ARGS% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        set "ERR=%ERRORLEVEL%"
        popd >nul 2>&1
        endlocal & exit /b %ERR%
    )
)

call "%VENV_PY%" -m pip --version >nul 2>&1
if errorlevel 1 (
    call %PY_CMD% %PY_ARGS% -m venv --upgrade-deps "%VENV_DIR%"
)

call "%VENV_PY%" -m pip --version >nul 2>&1
if errorlevel 1 (
    call "%VENV_PY%" -m ensurepip --upgrade >nul 2>&1
)

call "%VENV_PY%" -m pip --version >nul 2>&1
if errorlevel 1 (
    set "GETPIP_FILE=%TEMP%\get-pip.py"
    for %%P in (powershell.exe pwsh.exe) do (
        where /Q %%P 2>nul
        if not errorlevel 1 (
            %%P -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile '%GETPIP_FILE%'" 2>nul
            goto :after_getpip_download
        )
    )
    echo [INFO] Downloading get-pip.py via bitsadmin fallback...
    bitsadmin /transfer getpipdownloadjob /download /priority normal https://bootstrap.pypa.io/get-pip.py "%GETPIP_FILE%" >nul 2>&1
:after_getpip_download
    if exist "%GETPIP_FILE%" (
        call "%VENV_PY%" "%GETPIP_FILE%"
        del /Q "%GETPIP_FILE%" >nul 2>&1
    )
)

call "%VENV_PY%" -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] pip is not available in the virtual environment.
    set "ERR=1"
    popd >nul 2>&1
    endlocal & exit /b %ERR%
)

if exist requirements.txt (
    echo [INFO] Installing dependencies from requirements.txt
    call "%VENV_PY%" -m pip install -r requirements.txt --no-cache-dir
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed.
        set "ERR=%ERRORLEVEL%"
        popd >nul 2>&1
        endlocal & exit /b %ERR%
    )
) else (
    echo [WARN] requirements.txt not found, skipping dependency installation.
)

echo [INFO] Starting WebWork...
call "%VENV_PY%" -X utf8 main.py %*
set "EXIT_CODE=%ERRORLEVEL%"

popd >nul 2>&1
endlocal & exit /b %EXIT_CODE%

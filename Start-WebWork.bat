@echo off
setlocal
REM One-click launcher: reliable arg passing to PowerShell and UTF-8 console
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap.ps1" %*
endlocal

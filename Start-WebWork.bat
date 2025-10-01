@echo off
setlocal
REM One-click launcher: reliable arg passing to PowerShell
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap.ps1" %*
endlocal

@echo off
setlocal
REM One-click launcher: runs PowerShell with temporary policy bypass and UTF-8
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; ^
   $env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'; ^
   & '%~dp0bootstrap.ps1' @args"
endlocal

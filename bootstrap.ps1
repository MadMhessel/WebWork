#requires -Version 5.1
param(
  [Parameter(ValueFromRemainingArguments=$true)]
  [string[]]$AppArgs
)

$ErrorActionPreference = "Stop"

# 0) Work in script directory
Set-Location -LiteralPath (Split-Path -Parent $MyInvocation.MyCommand.Path)

# 1) TLS 1.2 for downloads
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# 2) Ensure uv (official installer; winget fallback)
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  try { iex (irm "https://astral.sh/uv/install.ps1") } catch {
    try { winget install --id=astral-sh.uv -e --source winget --silent | Out-Null } catch { }
  }
}

# Ensure we can reach uv.exe even if the installer modified only the user PATH.
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  $candidatePaths = @()
  if ($env:USERPROFILE) { $candidatePaths += Join-Path $env:USERPROFILE ".local\bin\uv.exe" }
  if ($env:LOCALAPPDATA) { $candidatePaths += Join-Path $env:LOCALAPPDATA "Programs\uv\uv.exe" }

  foreach ($candidate in $candidatePaths) {
    if (-not $candidate) { continue }
    if (-not (Test-Path $candidate)) { continue }

    $dir = Split-Path -Parent $candidate
    if (-not $dir) { continue }

    $pathEntries = $env:Path -split ';'
    if (-not ($pathEntries | Where-Object { $_ -and ($_ -ieq $dir) })) {
      $env:Path = "$dir;$env:Path"
    }
  }
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv is not available" }

# 3) Create venv if missing
if (-not (Test-Path ".venv")) { uv venv | Out-Null }

$venvPython = Join-Path ".venv" "Scripts/python.exe"
if (-not (Test-Path $venvPython)) {
  $venvPython = Join-Path ".venv" "bin/python"
}
if (-not (Test-Path $venvPython)) { throw "Python executable not found in virtual environment" }

# 4) Dependencies (wheel-first) + minimal guarantees
if (Test-Path "requirements.txt") {
  $req = Get-Content "requirements.txt" -Raw

  # Pillow must support Python 3.13
  $reqNew = $req -replace '(?im)^\s*Pillow\s*==\s*10\.\d+\.\d+\s*$', 'Pillow==11.0.0'
  if ($reqNew -ne $req) { Set-Content "requirements.txt" $reqNew; $req = $reqNew }

  # Ensure python-dotenv & platformdirs
  if ($req -notmatch "(?im)^\s*python-dotenv(\b|==|>=)") { Add-Content "requirements.txt" "`npython-dotenv>=1.0.0" }
  if ($req -notmatch "(?im)^\s*platformdirs(\b|==|>=)") { Add-Content "requirements.txt" "`nplatformdirs>=4.0.0" }

  # Replace legacy tgcrypto (sdist) with drop-in wheel
  if ($req -match "(?im)^\s*tgcrypto(\b|==|>=)") {
    $req2 = ($req -replace "(?im)^\s*tgcrypto.*$", "# tgcrypto disabled on CPython 3.12+: wheelless sdist causes MSVC build")
    Set-Content "requirements.txt" $req2
    if ($req2 -notmatch "(?im)^\s*TgCrypto-pyrofork(\b|==|>=)") {
      Add-Content "requirements.txt" "`nTgCrypto-pyrofork>=1.2.7"
    }
  }

  & $venvPython -m pip install --upgrade pip
  & $venvPython -m pip install -r "requirements.txt"
} else {
  & $venvPython -m pip install --upgrade pip
  & $venvPython -m pip install python-dotenv>=1.0.0 platformdirs>=4.0.0
}

# 5) Run app and forward user args
if ($AppArgs.Count -gt 0) {
  & $venvPython "./main.py" @AppArgs
} else {
  & $venvPython "./main.py"
}

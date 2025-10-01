$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Split-Path -Parent $MyInvocation.MyCommand.Path)

# 1) Ensure uv is available (installer or winget fallback).
try {
  if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv..."
    iex (irm "https://astral.sh/uv/install.ps1")
  }
} catch {
  Write-Warning "uv install via script failed; trying winget..."
  try { winget install --id=astral-sh.uv -e --source winget --silent | Out-Null } catch { }
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  throw "uv is not available. Install uv manually: https://docs.astral.sh/uv/"
}

# 2) Ensure a Python runtime (uv can fetch automatically). Prefer 3.11 LTS band.
try { uv python install 3.11 --default | Out-Null } catch { }

# 3) Create venv if missing and sync dependencies.
if (-not (Test-Path ".venv")) { uv venv | Out-Null }

# Make sure requirements exist; enforce minimal extras.
if (Test-Path "requirements.txt") {
  $req = Get-Content "requirements.txt" -Raw
  if ($req -notmatch "(?im)^\s*python-dotenv(\b|==|>=)") {
    Add-Content "requirements.txt" "`npython-dotenv>=1.0.0"
  }
  if ($req -match "(?im)^\s*TgCrypto(\b|==|>=)") {
    Write-Host "Adding TgCrypto-pyrofork for prebuilt wheels on CPython 3.12+"
    Add-Content "requirements.txt" "`nTgCrypto-pyrofork>=1.2.7"
  }
  uv sync --no-dev
} else {
  uv pip install python-dotenv
}

# 4) Run the app (forward any args given to the BAT).
$argv = $args
if ($argv.Count -gt 0) {
  uv run python .\main.py @argv
} else {
  uv run python .\main.py
}

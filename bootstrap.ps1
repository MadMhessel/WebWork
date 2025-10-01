#requires -Version 5.1
$ErrorActionPreference = "Stop"

param(
  [Parameter(ValueFromRemainingArguments=$true)]
  [string[]]$AppArgs
)

# 0) Work in script directory
Set-Location -LiteralPath (Split-Path -Parent $MyInvocation.MyCommand.Path)

# 1) Ensure TLS 1.2 for web downloads
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# 2) Ensure uv is available (official installer first, winget as fallback)
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  try {
    Write-Host "Installing uv..."
    iex (irm "https://astral.sh/uv/install.ps1")
  } catch {
    Write-Warning "uv script install failed; trying winget..."
    try { winget install --id=astral-sh.uv -e --source winget --silent | Out-Null } catch { }
  }
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  throw "uv is not available. See: https://docs.astral.sh/uv/"
}

# 3) Create venv if missing (uv will fetch a suitable Python automatically)
if (-not (Test-Path ".venv")) { uv venv | Out-Null }

# 4) Dependencies from requirements.txt (prefer wheels) + minimal guarantees
if (Test-Path "requirements.txt") {
  $req = Get-Content "requirements.txt" -Raw
  if ($req -notmatch "(?im)^\s*python-dotenv(\b|==|>=)") {
    Add-Content "requirements.txt" "`npython-dotenv>=1.0.0"
  }
  if ($req -match "(?im)^\s*TgCrypto(\b|==|>=)") {
    Write-Host "Detected TgCrypto -> adding TgCrypto-pyrofork for wheels on CPython 3.12+"
    if ($req -notmatch "(?im)^\s*TgCrypto-pyrofork(\b|==|>=)") {
      Add-Content "requirements.txt" "`nTgCrypto-pyrofork>=1.2.7"
    }
  }
  uv sync --no-dev
} else {
  uv pip install python-dotenv
}

# 5) Run app and forward user args (e.g., --loop)
if ($AppArgs.Count -gt 0) {
  uv run python .\main.py @AppArgs
} else {
  uv run python .\main.py
}

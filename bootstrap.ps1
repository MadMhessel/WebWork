#requires -Version 5.1
$ErrorActionPreference = "Stop"

param(
  [Parameter(ValueFromRemainingArguments=$true)]
  [string[]]$AppArgs
)

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
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv is not available" }

# 3) Create venv if missing
if (-not (Test-Path ".venv")) { uv venv | Out-Null }

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

  uv sync --no-dev
} else {
  uv pip install python-dotenv platformdirs
}

# 5) Run app and forward user args
if ($AppArgs.Count -gt 0) { uv run python .\main.py @AppArgs } else { uv run python .\main.py }

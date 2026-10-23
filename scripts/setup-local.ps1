$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python Launcher not found. Install Python 3.12 from https://www.python.org/downloads/windows/ and rerun this script."
}
$pyVersion = & py -3.12 --version 2>&1
if ($LASTEXITCODE -ne 0 -or $pyVersion -notmatch 'Python 3\.12') {
    throw "Python 3.12 not found. Found: $pyVersion. Install Python 3.12 and rerun."
}

if (-not (Test-Path '.venv')) {
    & py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Python virtual environment." }
}
$python = Join-Path $Root '.venv\Scripts\python.exe'
& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }
& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }

if (-not (Test-Path '.env')) {
    Copy-Item '.env.example' '.env'
    Write-Host "Created .env from .env.example. Database setup will replace the local app password in DATABASE_URL." -ForegroundColor Yellow
} else {
    Write-Host "Existing .env preserved. Review Pinecone and n8n Cloud settings manually; this script never overwrites secrets."
}

Write-Host "`nPython environment is ready." -ForegroundColor Green
Write-Host "Next, ensure PostgreSQL 16 is running, then run: .\scripts\setup-local-db.ps1"
Write-Host "After editing .env with your Pinecone/AI/voice settings, run: .\scripts\run-local.ps1"

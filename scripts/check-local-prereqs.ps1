$ErrorActionPreference = 'Continue'
Write-Host "Saathi local prerequisite check" -ForegroundColor Cyan
Write-Host "This checks the current Windows shell only; it does not install software or inspect other machines."

$missing = @()
$pythonOk = $false
if (Get-Command py -ErrorAction SilentlyContinue) {
    $v = & py -3.12 --version 2>$null
    if ($LASTEXITCODE -eq 0 -and $v -match 'Python 3\.12') {
        Write-Host "[OK] $v"
        $pythonOk = $true
    } else { Write-Host "[MISSING] Python 3.12 (Python Launcher exists, but 3.12 was not found)" }
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $v = & python --version 2>$null
    if ($LASTEXITCODE -eq 0 -and $v -match 'Python 3\.12') { Write-Host "[OK] $v"; $pythonOk = $true }
    else { Write-Host "[MISSING] Python 3.12; found $v" }
} else { Write-Host "[MISSING] Python 3.12" }
if (-not $pythonOk) { $missing += 'Python 3.12' }

$psql = Get-Command psql -ErrorAction SilentlyContinue
if (-not $psql) {
    $candidate = Get-ChildItem 'C:\Program Files\PostgreSQL\*\bin\psql.exe' -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
    if ($candidate) { $psql = @{ Source = $candidate.FullName } }
}
if ($psql) {
    Write-Host "[OK] PostgreSQL client: $($psql.Source)"
    $services = Get-Service -Name 'postgresql*' -ErrorAction SilentlyContinue
    if ($services) {
        $services | ForEach-Object { Write-Host "      Service: $($_.Name), Status: $($_.Status)" }
        if (-not ($services | Where-Object { $_.Status -eq 'Running' })) {
            Write-Host "[ACTION] A PostgreSQL service is installed but not running. Start it from Windows Services before database setup." -ForegroundColor Yellow
        }
    } else {
        Write-Host "[MISSING] PostgreSQL Windows service not found; psql alone is not a database server. Install PostgreSQL Server and its command-line tools." -ForegroundColor Yellow
        $missing += 'PostgreSQL server service'
    }
} else { Write-Host "[MISSING] PostgreSQL 16 (server and psql command-line tool)"; $missing += 'PostgreSQL 16' }

if (Get-Command git -ErrorAction SilentlyContinue) { Write-Host "[OK] Git (optional)" } else { Write-Host "[OPTIONAL] Git not found; not required to run the extracted ZIP." }
if (Get-Command docker -ErrorAction SilentlyContinue) { Write-Host "[OK] Docker (optional; not needed for native setup)" } else { Write-Host "[OPTIONAL] Docker not found; not required for native setup or n8n Cloud." }
if (Get-Command node -ErrorAction SilentlyContinue) { Write-Host "[OK] Node.js (optional; used only for the JavaScript syntax check)" } else { Write-Host "[OPTIONAL] Node.js not found; the frontend does not need Node.js to run." }
if (Test-Path '.env') { Write-Host "[OK] .env exists (do not share it)" } else { Write-Host "[NEXT] .env not found; setup-local.ps1 will create it from .env.example." }

if ($missing.Count -gt 0) {
    Write-Host "`nInstall these required applications:" -ForegroundColor Yellow
    $missing | ForEach-Object { Write-Host " - $_" }
    Write-Host "Python: https://www.python.org/downloads/windows/"
    Write-Host "PostgreSQL: https://www.postgresql.org/download/windows/"
    exit 1
}
Write-Host "`nRequired command-line prerequisites look present. Pinecone and n8n Cloud credentials are configured separately in .env / their service UIs." -ForegroundColor Green

param(
    [string]$DatabaseName = 'wellness',
    [string]$AppRole = 'wellness_app'
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$psqlCmd = Get-Command psql -ErrorAction SilentlyContinue
if (-not $psqlCmd) {
    $candidate = Get-ChildItem 'C:\Program Files\PostgreSQL\*\bin\psql.exe' -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
    if ($candidate) { $psqlPath = $candidate.FullName } else { throw "psql.exe not found. Install PostgreSQL 16 and add its bin directory to PATH." }
} else { $psqlPath = $psqlCmd.Source }

$adminSecure = Read-Host 'PostgreSQL administrator password for user postgres' -AsSecureString
$adminPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($adminSecure)
$adminPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($adminPtr)
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($adminPtr)

# Generate a high-entropy hex-only app password, avoiding URL-encoding surprises in DATABASE_URL.
$appPassword = ([guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')).ToLowerInvariant()
$sqlLiteral = $appPassword.Replace("'", "''")
$env:PGPASSWORD = $adminPassword
try {
    & $psqlPath -h localhost -U postgres -d postgres -v ON_ERROR_STOP=1 -tAc "SELECT 1"
    if ($LASTEXITCODE -ne 0) { throw "Could not connect as PostgreSQL user postgres. Verify the service/password." }

    $roleOutput = & $psqlPath -h localhost -U postgres -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='$AppRole'"
    if ($LASTEXITCODE -ne 0) { throw "Could not check PostgreSQL application role." }
    # The query returns no rows when the role does not exist; normalize null output to an empty string.
    $roleExists = ([string]($roleOutput -join '')).Trim()
    if ($roleExists -eq '1') {
        & $psqlPath -h localhost -U postgres -d postgres -v ON_ERROR_STOP=1 -c "ALTER ROLE $AppRole WITH LOGIN PASSWORD '$sqlLiteral'"
    } else {
        & $psqlPath -h localhost -U postgres -d postgres -v ON_ERROR_STOP=1 -c "CREATE ROLE $AppRole WITH LOGIN PASSWORD '$sqlLiteral'"
    }
    if ($LASTEXITCODE -ne 0) { throw "Could not create/update PostgreSQL application role." }

    $dbOutput = & $psqlPath -h localhost -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DatabaseName'"
    if ($LASTEXITCODE -ne 0) { throw "Could not check PostgreSQL database." }
    # The query returns no rows when the database does not exist; normalize null output to an empty string.
    $dbExists = ([string]($dbOutput -join '')).Trim()
    if ($dbExists -eq '1') {
        & $psqlPath -h localhost -U postgres -d postgres -v ON_ERROR_STOP=1 -c "ALTER DATABASE $DatabaseName OWNER TO $AppRole"
    } else {
        & $psqlPath -h localhost -U postgres -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE $DatabaseName OWNER $AppRole"
    }
    if ($LASTEXITCODE -ne 0) { throw "Could not create/update the application database." }
} finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    $adminPassword = $null
    $adminSecure = $null
}

if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }
$envText = Get-Content '.env' -Raw
$dbUrl = "postgresql+psycopg://${AppRole}:${appPassword}@localhost:5432/${DatabaseName}"
if ($envText -match '(?m)^WELLNESS_DB_PASSWORD=.*$') { $envText = [regex]::Replace($envText, '(?m)^WELLNESS_DB_PASSWORD=.*$', "WELLNESS_DB_PASSWORD=$appPassword") }
if ($envText -match '(?m)^DATABASE_URL=.*$') { $envText = [regex]::Replace($envText, '(?m)^DATABASE_URL=.*$', "DATABASE_URL=$dbUrl") }
[System.IO.File]::WriteAllText((Join-Path $Root '.env'), $envText, [System.Text.UTF8Encoding]::new($false))
Write-Host "Database '$DatabaseName' and role '$AppRole' are ready. Local DATABASE_URL was written to .env." -ForegroundColor Green
Write-Host "No PostgreSQL administrator password was saved to .env. Keep the .env file private."

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path '.env')) { throw 'Missing .env' }
$pgDumpCmd = Get-Command pg_dump -ErrorAction SilentlyContinue
if (-not $pgDumpCmd) {
    $candidate = Get-ChildItem 'C:\Program Files\PostgreSQL\*\bin\pg_dump.exe' -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
    if ($candidate) { $pgDump = $candidate.FullName } else { throw 'pg_dump.exe not found. Install PostgreSQL command-line tools.' }
} else { $pgDump = $pgDumpCmd.Source }
$envValues = @{}
Get-Content '.env' | ForEach-Object { if ($_ -match '^\s*([^#=]+)=(.*)$') { $envValues[$matches[1].Trim()] = $matches[2].Trim().Trim('"') } }
$uri = [Uri]$envValues['DATABASE_URL'].Replace('postgresql+psycopg://','postgresql://')
$dbName = [Uri]::UnescapeDataString($uri.AbsolutePath.TrimStart('/'))
$port = if ($uri.Port -gt 0) { $uri.Port } else { 5432 }
$adminSecure = Read-Host 'PostgreSQL administrator password for user postgres' -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($adminSecure)
$adminPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
try {
    $env:PGPASSWORD = $adminPassword
    New-Item -ItemType Directory -Force -Path 'backups' | Out-Null
    $stamp = Get-Date -Format 'yyyyMMddTHHmmss'
    $out = Join-Path 'backups' "saathi-$stamp.dump"
    & $pgDump -h $uri.Host -p $port -U 'postgres' -d $dbName -Fc -f $out
    if ($LASTEXITCODE -ne 0) { Remove-Item $out -ErrorAction SilentlyContinue; throw 'pg_dump failed.' }
} finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    $adminPassword = $null
    $adminSecure = $null
}
Write-Host "Created database backup: $out" -ForegroundColor Green
Write-Host 'The dump is not encrypted by this script. Encrypt it with approved tooling and move it to access-controlled off-device storage.' -ForegroundColor Yellow

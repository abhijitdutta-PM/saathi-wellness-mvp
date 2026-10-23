param(
    [Parameter(Mandatory = $true)][string]$BackupFile,
    [string]$DatabaseName = 'wellness'
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$resolvedBackup = Resolve-Path $BackupFile -ErrorAction Stop
$pgRestoreCmd = Get-Command pg_restore -ErrorAction SilentlyContinue
if (-not $pgRestoreCmd) {
    $candidate = Get-ChildItem 'C:\Program Files\PostgreSQL\*\bin\pg_restore.exe' -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
    if ($candidate) { $pgRestore = $candidate.FullName } else { throw 'pg_restore.exe not found. Install PostgreSQL command-line tools.' }
} else { $pgRestore = $pgRestoreCmd.Source }
$confirmation = Read-Host "This overwrites objects in database '$DatabaseName'. Type RESTORE to continue"
if ($confirmation -cne 'RESTORE') { throw 'Restore cancelled.' }
$adminSecure = Read-Host 'PostgreSQL administrator password for user postgres' -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($adminSecure)
$adminPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
try {
    $env:PGPASSWORD = $adminPassword
    & $pgRestore -h 'localhost' -p 5432 -U 'postgres' -d $DatabaseName --clean --if-exists $resolvedBackup.Path
    if ($LASTEXITCODE -ne 0) { throw 'pg_restore failed. Check that the database and app role exist and the backup is compatible.' }
} finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    $adminPassword = $null
    $adminSecure = $null
}
Write-Host "Restore completed into '$DatabaseName'. Validate row counts, tenancy/RLS and app startup before use." -ForegroundColor Green

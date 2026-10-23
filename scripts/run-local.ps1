$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path '.env')) { throw "Missing .env. Run .\scripts\setup-local.ps1 first." }
$python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw "Python virtual environment missing. Run .\scripts\setup-local.ps1 first." }

Write-Host "Starting Saathi on http://127.0.0.1:8000 ..."
Write-Host "PowerShell can treat Uvicorn's normal stderr INFO logs as NativeCommandError when ErrorActionPreference is Stop. The setting is temporarily relaxed only while Uvicorn runs."

# Keep strict error handling for this script's own checks, but do not treat
# normal native-process stderr output (Uvicorn logs) as a terminating PowerShell error.
$previousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    & $python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 2>&1
    $serverExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousErrorActionPreference
}

if ($serverExitCode -ne 0) {
    throw "Uvicorn exited with code $serverExitCode. Review the preceding output for the actual application error."
}

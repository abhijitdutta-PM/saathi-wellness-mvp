$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path '.env')) { throw 'Missing .env. Run .\scripts\setup-local.ps1 first.' }

function New-HexSecret([int]$Bytes = 32) {
    $buffer = New-Object byte[] $Bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
    return [System.BitConverter]::ToString($buffer).Replace('-', '').ToLowerInvariant()
}

$contents = Get-Content '.env' -Raw
$updated = @()
foreach ($name in @('SECRET_KEY', 'N8N_WEBHOOK_SECRET', 'INTERNAL_API_SECRET')) {
    $pattern = "(?m)^$name=.*$"
    if ($contents -notmatch $pattern) { throw "Expected setting '$name' was not found in .env." }
    $replacement = "$name=$(New-HexSecret 32)"
    $regex = [regex]$pattern
    $contents = $regex.Replace($contents, [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $replacement }, 1)
    $updated += $name
}
[System.IO.File]::WriteAllText((Join-Path $Root '.env'), $contents, [System.Text.UTF8Encoding]::new($false))
Write-Host 'Generated new local secrets for:' -ForegroundColor Green
$updated | ForEach-Object { Write-Host " - $_" }
Write-Host 'Secret values were not displayed. Copy N8N_WEBHOOK_SECRET from .env into the n8n Cloud Header Auth credential locally.' -ForegroundColor Yellow

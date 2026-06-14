$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Runtime = Join-Path $Root "research\verification"
$PidPath = Join-Path $Runtime "runner.pid"
New-Item -ItemType Directory -Force -Path $Runtime | Out-Null

if (Test-Path $PidPath) {
    $ExistingPid = [int](Get-Content $PidPath)
    if (Get-Process -Id $ExistingPid -ErrorAction SilentlyContinue) {
        throw "Fixed verification is already running with PID $ExistingPid."
    }
    Remove-Item -LiteralPath $PidPath
}

& uv sync --project apps/api | Out-Null
$Executable = Join-Path $Root "apps\api\.venv\Scripts\trade3-verify-fixed.exe"
if (-not (Test-Path $Executable)) {
    throw "Verification executable was not installed: $Executable"
}

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Stdout = Join-Path $Runtime "runner-$Stamp.log"
$Stderr = Join-Path $Runtime "runner-$Stamp.err.log"
$Arguments = @("--config", "research/verification/config.json")
$Process = Start-Process -FilePath $Executable -ArgumentList $Arguments `
    -WorkingDirectory $Root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr
$Process.Id | Set-Content -Path $PidPath -Encoding ascii

Write-Host "Fixed verification started."
Write-Host "PID: $($Process.Id)"
Write-Host "Status: .\scripts\status_fixed_verification.ps1"

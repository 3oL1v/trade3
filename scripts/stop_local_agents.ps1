$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$PidPath = Join-Path $Root "local_agents\runtime\worker.pid"

if (-not (Test-Path $PidPath)) {
    Write-Host "Local agent worker is not running."
    exit 0
}

$WorkerPid = [int](Get-Content $PidPath)
$Worker = Get-Process -Id $WorkerPid -ErrorAction SilentlyContinue
if ($Worker) {
    Stop-Process -Id $WorkerPid
    Wait-Process -Id $WorkerPid -ErrorAction SilentlyContinue
    Write-Host "Stopped local agent worker PID $WorkerPid."
}
else {
    Write-Host "Worker PID $WorkerPid was already stopped."
}
Remove-Item -LiteralPath $PidPath

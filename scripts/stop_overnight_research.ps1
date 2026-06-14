$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$PidPath = Join-Path $Root "research\overnight\runner.pid"

if (-not (Test-Path $PidPath)) {
    Write-Host "Overnight research is not running."
    exit 0
}

$RunnerPid = [int](Get-Content $PidPath)
$Process = Get-Process -Id $RunnerPid -ErrorAction SilentlyContinue
if ($Process) {
    Stop-Process -Id $RunnerPid
    Wait-Process -Id $RunnerPid -ErrorAction SilentlyContinue
    Write-Host "Stopped overnight research PID $RunnerPid."
}
else {
    Write-Host "Runner PID $RunnerPid was already stopped."
}
Remove-Item -LiteralPath $PidPath

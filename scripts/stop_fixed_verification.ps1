$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$PidPath = Join-Path $Root "research\verification\runner.pid"

if (-not (Test-Path $PidPath)) {
    Write-Host "Fixed verification is not running."
    exit 0
}

$RunnerPid = [int](Get-Content $PidPath)
$Process = Get-Process -Id $RunnerPid -ErrorAction SilentlyContinue
if ($Process) {
    Stop-Process -Id $RunnerPid
    Wait-Process -Id $RunnerPid -ErrorAction SilentlyContinue
    Write-Host "Stopped fixed verification PID $RunnerPid."
}
else {
    Write-Host "Runner PID $RunnerPid was already stopped."
}
Remove-Item -LiteralPath $PidPath

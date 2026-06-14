$Root = Split-Path $PSScriptRoot -Parent
$Runtime = Join-Path $Root "research\verification"
$PidPath = Join-Path $Runtime "runner.pid"

if (Test-Path $PidPath) {
    $RunnerPid = [int](Get-Content $PidPath)
    if (Get-Process -Id $RunnerPid -ErrorAction SilentlyContinue) {
        Write-Host "Runner: RUNNING (PID $RunnerPid)"
    }
    else {
        Write-Host "Runner: STOPPED (stale PID $RunnerPid)"
    }
}
else {
    Write-Host "Runner: NOT STARTED"
}

$LatestPath = Join-Path $Runtime "latest-run.txt"
if (Test-Path $LatestPath) {
    $Run = Get-Content $LatestPath
    Write-Host "Run: $Run"
    $StatePath = Join-Path $Run "state.json"
    if (Test-Path $StatePath) {
        Get-Content $StatePath
    }
    $SummaryPath = Join-Path $Run "summary.json"
    if (Test-Path $SummaryPath) {
        $Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
        Write-Host "Decision:"
        $Summary.decision | Format-List
    }
}

$LatestLog = Get-ChildItem $Runtime -Filter "runner-*.log" -File |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if ($LatestLog) {
    Write-Host "Recent log:"
    Get-Content $LatestLog.FullName -Tail 12
}

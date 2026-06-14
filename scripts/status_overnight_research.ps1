$Root = Split-Path $PSScriptRoot -Parent
$Runtime = Join-Path $Root "research\overnight"
$PidPath = Join-Path $Runtime "runner.pid"

if (Test-Path $PidPath) {
    $RunnerPid = [int](Get-Content $PidPath)
    $Process = Get-Process -Id $RunnerPid -ErrorAction SilentlyContinue
    if ($Process) {
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
    $LeaderboardPath = Join-Path $Run "leaderboard.json"
    if (Test-Path $LeaderboardPath) {
        $Leaders = Get-Content $LeaderboardPath -Raw | ConvertFrom-Json
        Write-Host "Top trials:"
        $Leaders | Select-Object -First 5 `
            trial, research_score, source, `
            @{Name = "train_exp"; Expression = { $_.train.expectancy_r }}, `
            @{Name = "validation_exp"; Expression = { $_.validation.expectancy_r }} |
            Format-Table -AutoSize
    }
}

$LatestLog = Get-ChildItem $Runtime -Filter "runner-*.log" -File |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if ($LatestLog) {
    Write-Host "Recent log:"
    Get-Content $LatestLog.FullName -Tail 12
}

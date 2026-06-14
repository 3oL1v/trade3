$Root = Split-Path $PSScriptRoot -Parent
$Base = Join-Path $Root "local_agents"
$PidPath = Join-Path $Base "runtime\worker.pid"

if (Test-Path $PidPath) {
    $WorkerPid = [int](Get-Content $PidPath)
    $Worker = Get-Process -Id $WorkerPid -ErrorAction SilentlyContinue
    if ($Worker) {
        Write-Host "Worker: RUNNING (PID $WorkerPid)"
    }
    else {
        Write-Host "Worker: STOPPED (stale PID $WorkerPid)"
    }
}
else {
    Write-Host "Worker: NOT STARTED"
}

$DaemonState = Join-Path $Root ".claude-flow\daemon-state.json"
if (Test-Path $DaemonState) {
    $Daemon = Get-Content $DaemonState -Raw | ConvertFrom-Json
    Write-Host "Generic Ruflo daemon: $(if ($Daemon.running) { 'WARNING: RUNNING' } else { 'STOPPED' })"
}

foreach ($Name in @("inbox", "running", "done", "failed", "reports")) {
    $Path = Join-Path $Base $Name
    $Count = if (Test-Path $Path) {
        $Filter = if ($Name -eq "reports") { "*.md" } else { "*.json" }
        @(Get-ChildItem -LiteralPath $Path -Filter $Filter -File -ErrorAction SilentlyContinue).Count
    }
    else {
        0
    }
    Write-Host "$Name`: $Count"
}

$Latest = Get-ChildItem (Join-Path $Base "reports") -Filter "*.md" -File `
    -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if ($Latest) {
    Write-Host "`nLatest report: $($Latest.FullName)"
    Get-Content $Latest.FullName -Encoding utf8 -TotalCount 35
}

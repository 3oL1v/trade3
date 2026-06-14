param(
    [double]$MaxHours = 7,
    [int]$MaxTrials = 500
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Runtime = Join-Path $Root "research\overnight"
$PidPath = Join-Path $Runtime "runner.pid"
New-Item -ItemType Directory -Force -Path $Runtime | Out-Null

if (Test-Path $PidPath) {
    $ExistingPid = [int](Get-Content $PidPath)
    if (Get-Process -Id $ExistingPid -ErrorAction SilentlyContinue) {
        throw "Overnight research is already running with PID $ExistingPid."
    }
    Remove-Item -LiteralPath $PidPath
}

try {
    Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3 | Out-Null
}
catch {
    $Ollama = (Get-Command ollama -ErrorAction Stop).Source
    Start-Process -FilePath $Ollama -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
    Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 10 | Out-Null
}

$PreviousErrorActionPreference = $ErrorActionPreference
try {
    # Ruflo emits normal ONNX startup messages on stderr.
    $ErrorActionPreference = "Continue"
    $AgentStorePath = Join-Path $Root ".claude-flow\agents\store.json"
    $AgentStore = if (Test-Path $AgentStorePath) {
        Get-Content $AgentStorePath -Raw
    }
    else {
        ""
    }
    if ($AgentStore -notmatch "Propose bounded JSON parameters for offline replay only") {
        & npx ruflo agent spawn -t researcher -n overnight-proposer -p ollama `
            -m qwen3.5:4b --task "Propose bounded JSON parameters for offline replay only." `
            --timeout 30 --auto-tools false 2>&1 | Out-Null
    }
    if ($AgentStore -notmatch "Critique bounded JSON parameters for offline replay only") {
        & npx ruflo agent spawn -t reviewer -n overnight-critic -p ollama `
            -m qwen3.5:4b --task "Critique bounded JSON parameters for offline replay only." `
            --timeout 30 --auto-tools false 2>&1 | Out-Null
    }
    $TaskStorePath = Join-Path $Root ".claude-flow\tasks\store.json"
    $TaskStore = if (Test-Path $TaskStorePath) {
        Get-Content $TaskStorePath -Raw
    }
    else {
        ""
    }
    if ($TaskStore -notmatch "Track the bounded overnight Trade3 parameter search") {
        & npx ruflo task create -t research `
            -d "Track the bounded overnight Trade3 parameter search; no order execution." `
            -p high --tags "trade3,overnight,ollama,offline" --timeout 86400 2>&1 | Out-Null
    }
}
finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
}

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Stdout = Join-Path $Runtime "runner-$Stamp.log"
$Stderr = Join-Path $Runtime "runner-$Stamp.err.log"
$Uv = (Get-Command uv -ErrorAction Stop).Source
$Arguments = @(
    "run",
    "--project",
    "apps/api",
    "trade3-overnight",
    "--config",
    "research/overnight/config.json",
    "--max-hours",
    $MaxHours,
    "--max-trials",
    $MaxTrials
)
$Process = Start-Process -FilePath $Uv -ArgumentList $Arguments `
    -WorkingDirectory $Root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr
$Process.Id | Set-Content -Path $PidPath -Encoding ascii

Write-Host "Overnight research started."
Write-Host "PID: $($Process.Id)"
Write-Host "stdout: $Stdout"
Write-Host "stderr: $Stderr"
Write-Host "Status: .\scripts\status_overnight_research.ps1"

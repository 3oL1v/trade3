param(
    [switch]$Once
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Runtime = Join-Path $Root "local_agents\runtime"
$PidPath = Join-Path $Runtime "worker.pid"
New-Item -ItemType Directory -Force -Path $Runtime | Out-Null

if (Test-Path $PidPath) {
    $ExistingPid = [int](Get-Content $PidPath)
    if (Get-Process -Id $ExistingPid -ErrorAction SilentlyContinue) {
        throw "Local agent worker is already running with PID $ExistingPid."
    }
    Remove-Item -LiteralPath $PidPath
}

# Generic Ruflo daemon workers invoke Claude Code. Keep them stopped.
$PreviousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    & npx ruflo daemon stop 2>&1 | Out-Null
}
finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
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

$AgentStorePath = Join-Path $Root ".claude-flow\agents\store.json"
$AgentStore = if (Test-Path $AgentStorePath) {
    Get-Content $AgentStorePath -Raw
}
else {
    ""
}
$PreviousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    if ($AgentStore -notmatch "Plan bounded Trade3 tasks from supplied local context only") {
        & npx ruflo agent spawn -t researcher -n trade3-local-planner -p ollama `
            -m qwen3.5:4b --task "Plan bounded Trade3 tasks from supplied local context only." `
            --timeout 120 --auto-tools false 2>&1 | Out-Null
    }
    if ($AgentStore -notmatch "Critique bounded Trade3 plans from supplied local context only") {
        & npx ruflo agent spawn -t reviewer -n trade3-local-critic -p ollama `
            -m qwen3.5:4b --task "Critique bounded Trade3 plans from supplied local context only." `
            --timeout 120 --auto-tools false 2>&1 | Out-Null
    }
}
finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
}

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Stdout = Join-Path $Runtime "worker-$Stamp.log"
$Stderr = Join-Path $Runtime "worker-$Stamp.err.log"
$Uv = (Get-Command uv -ErrorAction Stop).Source
$Arguments = @(
    "run",
    "--project",
    "apps/api",
    "trade3-local-agents",
    "--config",
    "local_agents/config.json"
)
if ($Once) {
    $Arguments += "--once"
}
$Process = Start-Process -FilePath $Uv -ArgumentList $Arguments `
    -WorkingDirectory $Root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr
$Process.Id | Set-Content -LiteralPath $PidPath -Encoding ascii

Write-Host "Local Ollama worker started. PID: $($Process.Id)"
Write-Host "Queue: .\scripts\add_local_task.ps1 -Objective '...' -ContextFiles @('file1','file2')"
Write-Host "Status: .\scripts\status_local_agents.ps1"

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Host.UI.RawUI.WindowTitle = "TRADE3 LOCAL WORKER - Ollama planner + critic"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
chcp 65001 | Out-Null

Set-Location $Root
Write-Host "TRADE3 LOCAL WORKER" -ForegroundColor Cyan
Write-Host "Planner and critic: Ollama qwen3.5:4b"
Write-Host "Ruflo generic daemon: disabled"
Write-Host "This window shows task progress. Press Ctrl+C to stop.`n"

$Runtime = Join-Path $Root "local_agents\runtime"
$PidPath = Join-Path $Runtime "worker.pid"
New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
$PID | Set-Content -LiteralPath $PidPath -Encoding ascii

try {
    & uv run --project apps/api trade3-local-agents --config local_agents/config.json
}
finally {
    if (Test-Path $PidPath) {
        $StoredPid = [int](Get-Content $PidPath)
        if ($StoredPid -eq $PID) {
            Remove-Item -LiteralPath $PidPath
        }
    }
    Write-Host "`nWorker stopped." -ForegroundColor Yellow
}

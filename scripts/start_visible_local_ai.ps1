$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Runtime = Join-Path $Root "local_agents\runtime"
$WindowsPath = Join-Path $Runtime "visible-windows.json"
New-Item -ItemType Directory -Force -Path $Runtime | Out-Null

# Stop the old hidden worker before starting its visible replacement.
& (Join-Path $PSScriptRoot "stop_local_agents.ps1")

try {
    Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3 | Out-Null
}
catch {
    $Ollama = (Get-Command ollama -ErrorAction Stop).Source
    Start-Process -FilePath $Ollama -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
}

$PowerShell = (Get-Command powershell.exe -ErrorAction Stop).Source
function Start-VisibleConsole([string]$ScriptPath) {
    Start-Process -FilePath $PowerShell `
        -ArgumentList @(
            "-NoExit",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "`"$ScriptPath`""
        ) `
        -WorkingDirectory $Root -WindowStyle Normal -PassThru
}

$Worker = Start-VisibleConsole (Join-Path $PSScriptRoot "run_local_worker_console.ps1")
$Ruflo = Start-VisibleConsole (Join-Path $PSScriptRoot "ruflo_control_console.ps1")
$Ollama = Start-VisibleConsole (Join-Path $PSScriptRoot "run_ollama_chat.ps1")

[ordered]@{
    started_at = (Get-Date).ToUniversalTime().ToString("o")
    worker_window_pid = $Worker.Id
    ruflo_window_pid = $Ruflo.Id
    ollama_window_pid = $Ollama.Id
} | ConvertTo-Json | Set-Content -LiteralPath $WindowsPath -Encoding utf8

Write-Host "Visible local AI consoles started:"
Write-Host "  OLLAMA CHAT PID: $($Ollama.Id)"
Write-Host "  RUFLO CONTROL PID: $($Ruflo.Id)"
Write-Host "  LOCAL WORKER PID: $($Worker.Id)"

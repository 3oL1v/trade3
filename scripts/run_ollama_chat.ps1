$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Host.UI.RawUI.WindowTitle = "OLLAMA CHAT - qwen3.5:4b"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
chcp 65001 | Out-Null

Set-Location $Root
while ($true) {
    Clear-Host
    Write-Host "OLLAMA INTERACTIVE CHAT" -ForegroundColor Green
    Write-Host "Model: qwen3.5:4b"
    Write-Host "Type prompts directly. Use /bye to exit."
    Write-Host "Russian input and output are supported."
    Write-Host "This chat is separate from the Ruflo task queue.`n"

    & ollama run qwen3.5:4b --think=false --keepalive 30m

    Write-Host "`nOllama chat has ended." -ForegroundColor Yellow
    $Choice = Read-Host "Press Enter to start a new chat or type Q to close this window"
    if ($Choice -match "^[Qq]$") {
        break
    }
}

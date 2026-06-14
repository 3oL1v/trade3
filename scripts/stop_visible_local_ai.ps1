$Root = Split-Path $PSScriptRoot -Parent
$WindowsPath = Join-Path $Root "local_agents\runtime\visible-windows.json"

if (-not (Test-Path $WindowsPath)) {
    Write-Host "Visible local AI consoles were not registered."
    exit 0
}

$Windows = Get-Content $WindowsPath -Encoding utf8 -Raw | ConvertFrom-Json
$Ids = @(
    $Windows.worker_window_pid,
    $Windows.ruflo_window_pid,
    $Windows.ollama_window_pid
) | Where-Object { $_ }

foreach ($Id in $Ids) {
    $Process = Get-Process -Id $Id -ErrorAction SilentlyContinue
    if ($Process) {
        Stop-Process -Id $Id
        Write-Host "Stopped console PID $Id."
    }
}
Remove-Item -LiteralPath $WindowsPath

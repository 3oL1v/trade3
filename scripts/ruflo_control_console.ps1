$ErrorActionPreference = "Continue"
$Root = Split-Path $PSScriptRoot -Parent
$Host.UI.RawUI.WindowTitle = "RUFLO CONTROL - Trade3 local queue"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
chcp 65001 | Out-Null
Set-Location $Root

function Show-Menu {
    Clear-Host
    Write-Host "RUFLO CONTROL / TRADE3 LOCAL QUEUE" -ForegroundColor Magenta
    Write-Host "Cloud daemon workers are disabled. Tasks execute through local Ollama.`n"
    Write-Host "1  Enter analysis prompt"
    Write-Host "2  Enter implementation-plan prompt"
    Write-Host "3  Review current Git diff"
    Write-Host "4  Queue / worker status"
    Write-Host "5  Show latest report"
    Write-Host "6  Open latest report in Notepad"
    Write-Host "7  Ruflo status"
    Write-Host "8  Ruflo agents"
    Write-Host "9  Run a custom Ruflo command"
    Write-Host "O  Open prompt editor (Notepad)"
    Write-Host "Q  Close this console"
}

function Add-InteractiveTask([string]$Mode, [string]$Objective = "") {
    if (-not $Objective) {
        $Objective = Read-Host "Prompt"
    }
    if (-not $Objective.Trim()) {
        Write-Host "Empty prompt ignored." -ForegroundColor Yellow
        return
    }
    $FilesInput = Read-Host "Context files, comma-separated (optional)"
    $Files = @()
    if ($FilesInput.Trim()) {
        $Files = @($FilesInput.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    }
    & (Join-Path $PSScriptRoot "add_local_task.ps1") `
        -Objective $Objective -Mode $Mode -ContextFiles $Files
}

function Get-LatestReport {
    Get-ChildItem (Join-Path $Root "local_agents\reports") -Filter "*.md" -File `
        -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}

$PreviousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    & npx ruflo start --skip-mcp 2>&1 | Out-Host
}
finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
}
Start-Sleep -Seconds 1

while ($true) {
    Show-Menu
    $Choice = (Read-Host "`nCommand").Trim().ToUpperInvariant()
    switch ($Choice) {
        "1" { Add-InteractiveTask "analyze" }
        "2" { Add-InteractiveTask "plan" }
        "3" {
            Add-InteractiveTask "review_diff" `
                "Review the current Trade3 Git diff. Find correctness, security, regression, and missing-test risks. Do not edit files."
        }
        "4" { & (Join-Path $PSScriptRoot "status_local_agents.ps1") }
        "5" {
            $Latest = Get-LatestReport
            if ($Latest) { Get-Content $Latest.FullName -Encoding utf8 }
            else { Write-Host "No reports yet." }
        }
        "6" {
            $Latest = Get-LatestReport
            if ($Latest) { Start-Process notepad.exe -ArgumentList $Latest.FullName }
            else { Write-Host "No reports yet." }
        }
        "7" { & npx ruflo status }
        "8" { & npx ruflo agent list }
        "9" {
            $Raw = Read-Host "ruflo arguments (example: memory list -n trade3-local)"
            if ($Raw.Trim()) {
                $Arguments = @($Raw -split "\s+" | Where-Object { $_ })
                & npx ruflo @Arguments
            }
        }
        "O" {
            $PromptPath = Join-Path $Root "local_agents\runtime\manual-prompt.txt"
            New-Item -ItemType Directory -Force -Path (Split-Path $PromptPath) | Out-Null
            if (-not (Test-Path $PromptPath)) {
                Set-Content -LiteralPath $PromptPath -Value "" -Encoding utf8
            }
            Start-Process notepad.exe -ArgumentList $PromptPath -Wait
            $Objective = (Get-Content -LiteralPath $PromptPath -Encoding utf8 -Raw).Trim()
            Add-InteractiveTask "analyze" $Objective
        }
        "Q" { return }
        default { Write-Host "Unknown command." -ForegroundColor Yellow }
    }
    Write-Host "`nPress Enter to return to menu."
    Read-Host | Out-Null
}

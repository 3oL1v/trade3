param(
    [Parameter(Mandatory = $true)]
    [string]$Objective,
    [ValidateSet("analyze", "plan", "review_diff")]
    [string]$Mode = "analyze",
    [string[]]$ContextFiles = @(),
    [string[]]$Acceptance = @()
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Inbox = Join-Path $Root "local_agents\inbox"
New-Item -ItemType Directory -Force -Path $Inbox | Out-Null

$Stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd-HHmmss")
$Suffix = -join ((97..122) | Get-Random -Count 6 | ForEach-Object { [char]$_ })
$TaskId = "task-$Stamp-$Suffix"
$Payload = [ordered]@{
    id = $TaskId
    objective = $Objective
    mode = $Mode
    context_files = @($ContextFiles)
    acceptance = @($Acceptance)
    created_at = (Get-Date).ToUniversalTime().ToString("o")
}
$TaskPath = Join-Path $Inbox "$TaskId.json"
$Payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $TaskPath -Encoding utf8

$PreviousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    & npx ruflo task create -t $Mode -d $Objective -p normal `
        --tags "trade3,local,ollama,no-cloud" --timeout 3600 2>&1 | Out-Null
}
finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
}

Write-Host "Queued: $TaskId"
Write-Host "File: $TaskPath"

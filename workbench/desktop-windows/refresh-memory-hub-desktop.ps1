$ErrorActionPreference = 'Stop'
$RepositoryRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ConfigPath = Join-Path $env:LOCALAPPDATA 'MemoryHubDesktopData\install.json'
if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw '桌面工作台尚未安装，请先运行 install-memory-hub-desktop.ps1。'
}
$Config = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
$SnapshotPath = $Config.snapshot

Push-Location $RepositoryRoot
try {
    python -m memory_hub snapshot --vault $Config.vault
} finally {
    Pop-Location
}

if (-not (Get-Process -Name 'MemoryHubDesktop' -ErrorAction SilentlyContinue)) {
    & (Join-Path $PSScriptRoot 'start-memory-hub-desktop.ps1')
}

Write-Output "Snapshot refreshed: $SnapshotPath"

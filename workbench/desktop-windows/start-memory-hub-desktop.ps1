$ErrorActionPreference = 'Stop'
$ConfigPath = Join-Path $env:LOCALAPPDATA 'MemoryHubDesktopData\install.json'
if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw '桌面工作台尚未安装，请先运行 install-memory-hub-desktop.ps1。'
}
$Config = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
$ExecutablePath = $Config.executable
$SnapshotPath = $Config.snapshot

if (-not $ExecutablePath -or -not (Test-Path -LiteralPath $ExecutablePath)) {
    throw '桌面工作台尚未安装，请先运行 install-memory-hub-desktop.ps1。'
}

$RainmeterProcess = Get-Process -Name 'Rainmeter' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($RainmeterProcess) {
    & $RainmeterProcess.Path '!DeactivateConfig' 'MemoryHubDock'
}

$Arguments = '--snapshot "{0}"' -f $SnapshotPath
Start-Process -FilePath $ExecutablePath -ArgumentList $Arguments -WorkingDirectory (Split-Path -Parent $ExecutablePath) -WindowStyle Hidden

param(
    [Parameter(Mandatory = $true)]
    [string]$Vault,
    [switch]$EnableStartup
)

$ErrorActionPreference = 'Stop'
$RepositoryRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$PublishRoot = Join-Path $env:TEMP 'memory-hub-desktop-publish'
$InstallBase = Join-Path $env:LOCALAPPDATA 'Programs\MemoryHubDesktop'
$DataRoot = Join-Path $env:LOCALAPPDATA 'MemoryHubDesktopData'
$ReleaseId = Get-Date -Format 'yyyyMMdd-HHmmss'
$InstallRoot = Join-Path $InstallBase "releases\$ReleaseId"
$VaultPath = [System.IO.Path]::GetFullPath($Vault)
$SnapshotPath = Join-Path $VaultPath '.memory-hub\runtime\operations_snapshot.json'
$ExecutablePath = Join-Path $InstallRoot 'MemoryHubDesktop.exe'

Push-Location $RepositoryRoot
try {
    python -m memory_hub snapshot --vault $VaultPath
} finally {
    Pop-Location
}

dotnet publish (Join-Path $PSScriptRoot 'MemoryHubDesktop.csproj') -c Release -r win-x64 --self-contained false -o $PublishRoot

$RunningProcesses = Get-Process -Name 'MemoryHubDesktop' -ErrorAction SilentlyContinue
if ($RunningProcesses) {
    $RunningProcesses | Stop-Process -Force
    $Deadline = (Get-Date).AddSeconds(10)
    do {
        Start-Sleep -Milliseconds 200
        $RemainingProcesses = Get-Process -Name 'MemoryHubDesktop' -ErrorAction SilentlyContinue
    } while ($RemainingProcesses -and (Get-Date) -lt $Deadline)
    if ($RemainingProcesses) {
        throw '旧版桌面工作台未能在 10 秒内退出，已停止安装以避免并行运行。'
    }
}
New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
Copy-Item -Path (Join-Path $PublishRoot '*') -Destination $InstallRoot -Recurse -Force
New-Item -ItemType Directory -Path $DataRoot -Force | Out-Null
@{ vault = $VaultPath; snapshot = $SnapshotPath; executable = $ExecutablePath } |
    ConvertTo-Json |
    Set-Content -LiteralPath (Join-Path $DataRoot 'install.json') -Encoding UTF8
@{ platform = 'windows'; snapshot = $SnapshotPath; executable = $ExecutablePath; release = $ReleaseId } |
    ConvertTo-Json |
    Set-Content -LiteralPath (Join-Path $VaultPath '.memory-hub\desktop-install.json') -Encoding UTF8

$Arguments = '--snapshot "{0}"' -f $SnapshotPath
$Shell = New-Object -ComObject WScript.Shell
$StartMenuPath = Join-Path ([Environment]::GetFolderPath('Programs')) 'AI记忆中枢桌面工作台.lnk'
$DesktopPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'AI记忆中枢桌面工作台.lnk'

foreach ($ShortcutPath in @($StartMenuPath, $DesktopPath)) {
    $Shortcut = $Shell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $ExecutablePath
    $Shortcut.Arguments = $Arguments
    $Shortcut.WorkingDirectory = $InstallRoot
    $Shortcut.Description = 'AI 记忆中枢高保真桌面任务工作台'
    $Shortcut.Save()
}

if ($EnableStartup) {
    $StartupPath = Join-Path ([Environment]::GetFolderPath('Startup')) 'AI记忆中枢桌面工作台.lnk'
    Copy-Item -LiteralPath $StartMenuPath -Destination $StartupPath -Force
}

$RainmeterProcess = Get-Process -Name 'Rainmeter' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($RainmeterProcess) {
    & $RainmeterProcess.Path '!DeactivateConfig' 'MemoryHubDock'
}

Start-Process -FilePath $ExecutablePath -ArgumentList $Arguments -WorkingDirectory $InstallRoot -WindowStyle Hidden
Write-Output "Installed: $ExecutablePath"
Write-Output "Release: $ReleaseId"
Write-Output "Snapshot: $SnapshotPath"
Write-Output "Startup enabled: $EnableStartup"

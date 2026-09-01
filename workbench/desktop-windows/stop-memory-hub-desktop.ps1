$Process = Get-Process -Name 'MemoryHubDesktop' -ErrorAction SilentlyContinue
if ($Process) {
    $Process | Stop-Process
    Write-Output 'AI 记忆中枢桌面工作台已关闭。'
} else {
    Write-Output 'AI 记忆中枢桌面工作台当前未运行。'
}

param([switch]$NoBrowser, [int]$WebWaitSeconds = 60)
# Teacher-local launcher for Windows PowerShell 5.1 and PowerShell 7.
# This file is saved as UTF-8 with BOM: Windows PowerShell 5.1 reads BOM-less files as ANSI.
# It only checks the machine, then runs the unchanged synthetic demo launcher.
$ErrorActionPreference = 'Stop'

function Fail([string]$Code, [string]$Message) {
    Write-Host ''
    Write-Host ('[' + $Code + '] ' + $Message) -ForegroundColor Red
    Write-Host '没有启动成功。请按上面的提示处理后重新双击；仍有问题请把本窗口截图发给我们。'
    exit 1
}

Write-Host '知界·仓颉学伴 - 教师本机测试启动器'
Write-Host '数据为合成数据，模型响应为确定性 Mock，编译反馈来自真实隔离 Runner；这不是教学成效结果。'
Write-Host ''

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail 'DOCKER_MISSING' '没有检测到 Docker Desktop。请先从 https://www.docker.com/products/docker-desktop/ 下载安装，安装后重启电脑，再重新双击本启动器。'
}

# One call tells us whether the engine is running and which kind of containers it uses.
$ErrorActionPreference = 'Continue'
$taskOsType = (& docker info --format '{{.OSType}}' 2>$null | Out-String).Trim()
$taskInfoExit = $LASTEXITCODE
$ErrorActionPreference = 'Stop'

if ($taskInfoExit -ne 0) {
    $taskHint = ''
    try {
        $taskVirtualization = (Get-CimInstance Win32_Processor | Select-Object -First 1).VirtualizationFirmwareEnabled
        if ($taskVirtualization -eq $false) { $taskHint = ' 另外，系统可能没有开启虚拟化，需要在电脑 BIOS 中开启 Virtualization (VT-x / SVM)。' }
    } catch { }
    Fail 'DOCKER_NOT_RUNNING' ('Docker Desktop 还没有启动。请从开始菜单打开 Docker Desktop，等左下角显示 Engine running 后再重新双击。' + $taskHint)
}
if ($taskOsType -ne 'linux') {
    Fail 'DOCKER_NOT_LINUX' 'Docker Desktop 当前使用的是 Windows 容器。请右键任务栏的 Docker 图标，选择 Switch to Linux containers 后重试。'
}

try {
    $taskMemoryGb = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
    if ($taskMemoryGb -lt 8) {
        Write-Host ('[提醒] 这台电脑内存约 ' + $taskMemoryGb + ' GB，建议 8 GB 以上，否则首次构建可能很慢或失败。') -ForegroundColor Yellow
    }
} catch { }

Write-Host '首次启动需要联网下载并构建镜像，可能需要十几分钟，请不要关闭本窗口。'
try {
    & (Join-Path $PSScriptRoot 'start-delivery.ps1')
} catch {
    Fail 'START_FAILED' ('演示服务没有启动成功：' + $_.Exception.Message + '。请确认网络可用、Docker Desktop 正常运行，并且 5209、8208 端口没有被其他程序占用。')
}

$taskReady = $false
$taskDeadline = (Get-Date).AddSeconds($WebWaitSeconds)
do {
    try {
        $taskPage = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5209/' -TimeoutSec 5
        if ($taskPage.StatusCode -eq 200) { $taskReady = $true; break }
    } catch { }
    Start-Sleep -Seconds 1
} while ((Get-Date) -lt $taskDeadline)
if (-not $taskReady) {
    Fail 'WEB_NOT_READY' '服务已启动，但网页 http://127.0.0.1:5209 暂时打不开。请等待一分钟后手动刷新；仍打不开请联系我们。'
}

# Give the generated demo password to the clipboard instead of printing it.
$taskEnvFile = Join-Path (Join-Path $PSScriptRoot '..') '.delivery/demo.env'
$taskCopied = $false
if (Test-Path -LiteralPath $taskEnvFile) {
    $taskLine = Get-Content -LiteralPath $taskEnvFile | Where-Object { $_ -match '^DEMO_PASSWORD=' } | Select-Object -First 1
    if ($taskLine) {
        try { Set-Clipboard -Value $taskLine.Substring('DEMO_PASSWORD='.Length); $taskCopied = $true } catch { }
    }
}

Write-Host ''
Write-Host '[TEACHER_LOCAL_READY] 已启动：http://127.0.0.1:5209' -ForegroundColor Green
Write-Host '教师账号：demo-teacher    学生账号：demo-student-1 到 demo-student-6'
if ($taskCopied) {
    Write-Host '登录密码已复制到剪贴板，在密码框里直接粘贴即可（不会显示在本窗口）。'
} else {
    Write-Host '登录密码在本目录的 .delivery\demo.env 文件里，名为 DEMO_PASSWORD 的那一行。请不要转发该文件。'
}
Write-Host '测试结束后，可在 Docker Desktop 里停止 knowbound-wave4-demo 项目，或运行：powershell -File scripts\start-delivery.ps1 -Action Stop'
if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:5209' }

param([string]$OutputPath, [string]$Ref = 'HEAD')
# Builds the teacher kit from COMMITTED files only (git archive), so ignored local files such as
# .delivery/demo.env, .delivery/live-model.env, .env and node_modules can never be included.
# Saved as UTF-8 with BOM so Windows PowerShell 5.1 shows the Chinese messages correctly.
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (-not $OutputPath) {
    $OutputPath = Join-Path $taskRoot ('.delivery/teacher-kit/knowbound-teacher-kit-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.zip')
}
$taskOutput = [IO.Path]::GetFullPath($OutputPath)
if (Test-Path -LiteralPath $taskOutput) { throw ('Refuse to overwrite an existing file: ' + $taskOutput) }

# Only what is needed to build and run the synthetic demo, plus the teacher guide.
$taskInclude = @('backend', 'frontend', 'runner', 'infra', 'data', 'scripts', 'start-teacher-local.cmd', 'docs/teacher-guide.md')
# Entries that must never travel to another machine, even if someone committed them by mistake.
$taskForbiddenSegments = @('.git', '.delivery', '.superpowers', '.venv', 'node_modules', '__pycache__')
$taskForbiddenFile = '(^|/)([^/]*\.env|\.env\.(?!example$)[^/]+|[^/]*\.(pem|key|pfx)|id_(rsa|ed25519)[^/]*)$'

$taskTemp = Join-Path ([IO.Path]::GetTempPath()) ('knowbound-kit-' + [Guid]::NewGuid().ToString('N') + '.zip')
try {
    Push-Location -LiteralPath $taskRoot
    try {
        $taskDirty = @(& git status --porcelain -- $taskInclude)
        if ($taskDirty.Count -gt 0) {
            Write-Warning '教师包只包含已提交的内容，工作区里尚未提交的修改不会进入教师包。'
        }
        & git archive --format=zip --prefix='knowbound-teacher-kit/' -o $taskTemp $Ref -- @taskInclude
        if ($LASTEXITCODE -ne 0) { throw 'git archive failed; make sure every included path is committed' }
    } finally { Pop-Location }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $taskArchive = [IO.Compression.ZipFile]::OpenRead($taskTemp)
    try { $taskNames = @($taskArchive.Entries | ForEach-Object { $_.FullName }) } finally { $taskArchive.Dispose() }
    foreach ($taskName in $taskNames) {
        $taskLower = $taskName.ToLowerInvariant()
        foreach ($taskSegment in $taskLower.Split('/')) {
            if ($taskForbiddenSegments -contains $taskSegment) { throw ('Refusing to package a forbidden path: ' + $taskName) }
        }
        if ($taskLower -match $taskForbiddenFile) { throw ('Refusing to package a possible secret: ' + $taskName) }
    }
    if (-not ($taskNames -contains 'knowbound-teacher-kit/start-teacher-local.cmd')) { throw 'The kit is missing start-teacher-local.cmd' }

    New-Item -ItemType Directory -Path (Split-Path -Parent $taskOutput) -Force | Out-Null
    Move-Item -LiteralPath $taskTemp -Destination $taskOutput
    Write-Output ('教师包已生成：' + $taskOutput)
    Write-Output ('共 ' + $taskNames.Count + ' 个文件，来自 ' + $Ref + ' 的已提交内容。不含密码、API Key、.delivery、node_modules。')
    Write-Output '请单独通过安全渠道告知演示登录方式；不要把 .delivery 目录或其中的文件发给任何人。'
} finally {
    if (Test-Path -LiteralPath $taskTemp) { Remove-Item -LiteralPath $taskTemp -Force }
}

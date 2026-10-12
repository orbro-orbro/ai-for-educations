param(
    [Parameter(Mandatory)][ValidatePattern('^[a-zA-Z0-9_-]+$')][string]$Name,
    [Parameter(Mandatory)][string]$Executable,
    [Parameter(Mandatory)][string[]]$CommandArguments,
    [Parameter(Mandatory)][string]$WorkingDirectory,
    [string]$EvidenceDirectory = (Join-Path $PSScriptRoot '../.superpowers/sdd/2026-10-12-wave4-task11-delivery/evidence')
)
$ErrorActionPreference = 'Stop'
$taskRun = Join-Path $EvidenceDirectory ($Name + '-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,8))
New-Item -ItemType Directory -Path $taskRun -Force | Out-Null
$taskLog = Join-Path $taskRun 'output.log'
$taskStarted = [DateTime]::UtcNow.ToString('o')
Push-Location -LiteralPath $WorkingDirectory
try {
    $taskHead = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Cannot bind evidence to source HEAD' }
    $taskDirty = @(& git status --porcelain --untracked-files=normal)
    $taskExit = 1
    try {
        & $Executable @CommandArguments 2>&1 | Tee-Object -FilePath $taskLog
        $taskExit = $LASTEXITCODE
    } finally {
        $taskRecord = [ordered]@{
            name=$Name; started_utc=$taskStarted; finished_utc=[DateTime]::UtcNow.ToString('o')
            head=$taskHead; working_tree=$taskDirty; cwd=(Get-Location).Path
            executable=$Executable; arguments=$CommandArguments; exit_code=$taskExit
            log='output.log'; sha256=(Get-FileHash -LiteralPath $taskLog -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        $taskRecord | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $taskRun 'command.json') -Encoding utf8
    }
} finally { Pop-Location }
if ($taskExit -ne 0) { throw ('Verification failed: ' + $Name + ' (exit ' + $taskExit + ')') }

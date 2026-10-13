param(
    [Parameter(Mandatory)][ValidatePattern('^[a-zA-Z0-9_-]+$')][string]$Name,
    [Parameter(Mandatory)][string]$Executable,
    [Parameter(Mandatory)][string[]]$CommandArguments,
    [Parameter(Mandatory)][string]$WorkingDirectory,
    [string[]]$ArtifactPaths = @(),
    [string]$EvidenceDirectory = (Join-Path $PSScriptRoot '../.superpowers/sdd/2026-10-12-wave4-task11-delivery/evidence')
)
$ErrorActionPreference = 'Stop'
$EvidenceDirectory=[IO.Path]::GetFullPath($EvidenceDirectory)
$taskRun = Join-Path $EvidenceDirectory ($Name + '-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,8))
New-Item -ItemType Directory -Path $taskRun -Force | Out-Null
$taskLog = Join-Path $taskRun 'output.log'
[IO.File]::WriteAllBytes($taskLog, [byte[]]@())
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
        $taskArtifacts=@()
        $taskPaths=@($ArtifactPaths)+@($CommandArguments | Where-Object { $_ -like '--junitxml=*' } | ForEach-Object { $_.Substring(11) })
        foreach($taskPath in ($taskPaths | Select-Object -Unique)) {
            if(Test-Path -LiteralPath $taskPath -PathType Leaf) {
                $taskFile=Get-Item -LiteralPath $taskPath
                $taskArtifacts+=@{path=$taskFile.FullName; sha256=(Get-FileHash -LiteralPath $taskFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant(); length=$taskFile.Length; modified_utc=$taskFile.LastWriteTimeUtc.ToString('o')}
            }
        }
        $taskRecord = [ordered]@{
            name=$Name; started_utc=$taskStarted; finished_utc=[DateTime]::UtcNow.ToString('o')
            head=$taskHead; working_tree=$taskDirty; cwd=(Get-Location).Path
            executable=$Executable; arguments=$CommandArguments; exit_code=$taskExit
            log='output.log'; sha256=(Get-FileHash -LiteralPath $taskLog -Algorithm SHA256).Hash.ToLowerInvariant()
            artifacts=$taskArtifacts
        }
        $taskRecord | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $taskRun 'command.json') -Encoding utf8
    }
} finally { Pop-Location }
if ($taskExit -ne 0) { throw ('Verification failed: ' + $Name + ' (exit ' + $taskExit + ')') }

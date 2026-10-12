param([Parameter(Mandatory)][string]$Python)
$ErrorActionPreference = 'Stop'
if ($env:DATABASE_URL) { throw 'DATABASE_URL must not override isolated regression fixtures' }
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskEnvFile = Join-Path $taskRoot '.superpowers/sdd/2026-10-12-wave4-task11-delivery/test.env'
$taskValues = @{}
foreach ($taskLine in Get-Content -LiteralPath $taskEnvFile) {
    if ($taskLine -match '^([A-Z0-9_]+)=(.*)$') { $taskValues[$Matches[1]] = $Matches[2] }
}
if ($taskValues['POSTGRES_PASSWORD'] -notmatch '^[a-f0-9]{32}$') { throw 'Dedicated synthetic credential missing or invalid' }
& $Python -B (Join-Path $taskRoot 'backend/scripts/delivery_environment.py')
if ($LASTEXITCODE -ne 0) { throw 'Dedicated resource labels not verified' }
$env:WAVE4_TEST_MODE = '1'
$taskUrl = 'postgresql+psycopg://knowbound:' + $taskValues['POSTGRES_PASSWORD'] + '@127.0.0.1:55440/'
$env:WAVE4_POSTGRES_URL = $taskUrl + 'wave4_router'
$env:TASK6_POSTGRES_URL = $taskUrl + 'wave4_task6'
$env:TASK7_POSTGRES_URL = $taskUrl + 'wave4_task7'
$env:TASK10_POSTGRES_URL = $taskUrl + 'wave4_task10'
$env:TASK6_RUNNER_ENDPOINT = 'http://127.0.0.1:8209'
$env:TASK7_RUNNER_ENDPOINT = 'http://127.0.0.1:8209'
$env:TASK10_RUNNER_IMAGE = $taskValues['RUNNER_SANDBOX_IMAGE']
$env:PYTHONDONTWRITEBYTECODE = '1'
Push-Location -LiteralPath (Join-Path $taskRoot 'backend')
try {
    & $Python -B -c 'from tests.integration.wave3_support import upgrade; upgrade("wave3_task6"); upgrade("wave3_task7", "0005_memories_audit"); upgrade("wave3_task10"); upgrade()'
    if ($LASTEXITCODE -ne 0) { throw 'Dedicated migration preparation failed' }
} finally { Pop-Location }
Write-Output 'Task 11 regression targets verified and prepared; credentials omitted.'

param([Parameter(Mandatory)][string]$RehearsalPath,[Parameter(Mandatory)][string]$OutputPath)
$ErrorActionPreference='Stop'
$taskInput=Get-Content -LiteralPath $RehearsalPath -Raw
$taskRehearsal=$taskInput | ConvertFrom-Json
if($taskRehearsal.timings.Count -ne 15 -or @($taskRehearsal.timings | Where-Object status -ne 'passed').Count -ne 0) { throw 'Read-only probe requires all 15 actual browser steps passed' }
$taskContainer='knowbound-wave4-demo-api-1'
$taskLabels=(& docker inspect $taskContainer --format '{{json .Config.Labels}}') | ConvertFrom-Json
if($LASTEXITCODE -ne 0 -or $taskLabels.'com.docker.compose.project' -ne 'knowbound-wave4-demo' -or $taskLabels.'knowbound.task' -ne 'wave4-task11-demo') { throw 'Read-only probe refuses a foreign API' }
$taskOutput=$taskInput | & docker exec -i $taskContainer python -m scripts.delivery_probe
if($LASTEXITCODE -ne 0) { throw 'Read-only authority probe failed' }
$taskOutput | ConvertFrom-Json | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputPath -Encoding utf8
$taskOutput

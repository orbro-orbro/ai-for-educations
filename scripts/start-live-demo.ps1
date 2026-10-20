param([ValidateSet('Start','Stop','Status')][string]$Action='Start', [switch]$NoBuild)
# Synthetic data + real model (DeepSeek or Qwen). Independent of start-delivery.ps1.
$ErrorActionPreference='Stop'
$taskRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskEnvFile=Join-Path $taskRoot '.delivery/live-model.env'
$taskProject='knowbound-live-demo'
if (!(Test-Path -LiteralPath $taskEnvFile)) {
    New-Item -ItemType Directory -Path (Split-Path $taskEnvFile) -Force | Out-Null
    @('# Fill in ONE provider key and MODEL_NAME, then re-run. This file is git-ignored; never commit it.',
      'MODEL_PROVIDER=deepseek','MODEL_NAME=','DEEPSEEK_API_KEY=','QWEN_API_KEY=','MODEL_BASE_URL=','MODEL_TIMEOUT_SECONDS=60',
      'APP_ENV=development','POSTGRES_DB=wave4_demo','POSTGRES_USER=knowbound',
      ('POSTGRES_PASSWORD='+[Guid]::NewGuid().ToString('N')),('AUTH_TOKEN_SECRET='+[Guid]::NewGuid().ToString('N')+[Guid]::NewGuid().ToString('N')),
      ('DEMO_PASSWORD='+[Guid]::NewGuid().ToString('N')),'API_PORT=8308','WEB_PORT=5309',
      'CORS_ALLOWED_ORIGINS=http://127.0.0.1:5309,http://localhost:5309','RUNNER_TIMEOUT_SECONDS=15','RUNNER_ENDPOINT=http://runner-controller:8080',
      'RUNNER_SANDBOX_IMAGE=knowbound-live-demo-sandbox:1','DOCKER_GID=0') | Set-Content -LiteralPath $taskEnvFile -Encoding ascii
    Start-Process notepad $taskEnvFile
    throw 'Live model configuration created at .delivery/live-model.env; MODEL_NAME and a provider key must be configured, then run again'
}
$taskConfig=@{}
foreach($taskLine in Get-Content -LiteralPath $taskEnvFile) {
    if($taskLine -match '^([A-Z0-9_]+)=(.*)$') { $taskConfig[$Matches[1]]=$Matches[2] }
}
$taskProvider=$taskConfig['MODEL_PROVIDER'].Trim().ToLowerInvariant()
$taskKeyVar=@{deepseek='DEEPSEEK_API_KEY';qwen='QWEN_API_KEY'}[$taskProvider]
if(!$taskKeyVar) { Start-Process notepad $taskEnvFile; throw 'MODEL_PROVIDER must be deepseek or qwen' }
if([string]::IsNullOrWhiteSpace($taskConfig['MODEL_NAME'])) { Start-Process notepad $taskEnvFile; throw 'MODEL_NAME must be configured' }
if([string]::IsNullOrWhiteSpace($taskConfig[$taskKeyVar])) { Start-Process notepad $taskEnvFile; throw ($taskKeyVar+' must be configured') }
foreach($taskPair in @(@('APP_ENV','development'),@('POSTGRES_DB','wave4_demo'),@('POSTGRES_USER','knowbound'),@('API_PORT','8308'),@('WEB_PORT','5309'),@('RUNNER_ENDPOINT','http://runner-controller:8080'),@('RUNNER_SANDBOX_IMAGE','knowbound-live-demo-sandbox:1'))) {
    if($taskConfig[$taskPair[0]] -ne $taskPair[1]) { throw ('Incompatible live demo configuration: '+$taskPair[0]) }
}
foreach($taskKey in @('POSTGRES_PASSWORD','DEMO_PASSWORD')) {
    if($taskConfig[$taskKey] -notmatch '^[a-f0-9]{32}$') { throw ('Explicit generated credential required: '+$taskKey) }
}
# Compose interpolation prefers host variables over the env file; refuse any conflict
# so a pre-set MODEL_BASE_URL or key can never redirect real credentials.
$taskGuardKeys=@($taskConfig.Keys)+@('MODEL_PROVIDER','MODEL_NAME','MODEL_BASE_URL','DEEPSEEK_API_KEY','QWEN_API_KEY','MODEL_LABEL') | Select-Object -Unique
foreach($taskKey in $taskGuardKeys) {
    $taskInherited=[Environment]::GetEnvironmentVariable($taskKey,'Process')
    $taskExpected=$taskConfig[$taskKey]
    if($taskKey -eq 'MODEL_LABEL') { $taskExpected=$null }
    if(![string]::IsNullOrEmpty($taskInherited) -and $taskInherited -ne $taskExpected) { throw ('Inherited environment conflicts with live demo configuration: '+$taskKey) }
}
$taskLabelName=@{deepseek='DeepSeek';qwen='Qwen'}[$taskProvider]
$env:MODEL_LABEL=($taskLabelName+' · '+$taskConfig['MODEL_NAME'])
Push-Location -LiteralPath $taskRoot
try {
    $taskIds=@(& docker ps -aq --filter ('name=^/'+$taskProject+'-'))
    if($LASTEXITCODE -ne 0) { throw 'Docker unavailable' }
    foreach($taskId in $taskIds) {
        $taskLabels=(& docker inspect $taskId --format '{{json .Config.Labels}}') | ConvertFrom-Json
        if($LASTEXITCODE -ne 0 -or $taskLabels.'knowbound.task' -ne 'live-model-demo' -or $taskLabels.'com.docker.compose.project' -ne $taskProject) { throw 'Refuse to modify a foreign container' }
    }
    $taskCompose=@('compose','--env-file',$taskEnvFile,'-p',$taskProject,'-f','infra/compose/docker-compose.yml','-f','infra/compose/docker-compose.live-model.yml')
    & docker @taskCompose config --quiet
    if($LASTEXITCODE -ne 0) { throw 'Live demo Compose configuration invalid' }
    if($Action -eq 'Start') {
        if(!$NoBuild) { & docker @taskCompose build; if($LASTEXITCODE -ne 0) { throw 'Live demo build failed' } }
        & docker @taskCompose up -d --no-build --wait --wait-timeout 180
        if($LASTEXITCODE -ne 0) { throw 'Live demo services did not reach healthy state' }
        Write-Output ('Live model demo ready: http://127.0.0.1:5309 ; API http://127.0.0.1:8308 ; model '+$env:MODEL_LABEL)
        Write-Output 'Synthetic actors; real model calls send synthetic code to the provider. Password is in ignored .delivery/live-model.env (DEMO_PASSWORD).'
        Start-Process 'http://127.0.0.1:5309'
    } elseif($Action -eq 'Stop') {
        & docker @taskCompose stop
        if($LASTEXITCODE -ne 0) { throw 'Live demo stop failed' }
    } else {
        & docker @taskCompose ps --all
        if($LASTEXITCODE -ne 0) { throw 'Live demo status failed' }
    }
} finally { Pop-Location }

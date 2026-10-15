param([ValidateSet('Start','Stop','Status')][string]$Action='Start', [switch]$NoBuild, [switch]$FreshData)
$ErrorActionPreference='Stop'
$taskRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskEnvFile=Join-Path $taskRoot '.delivery/demo.env'
$taskProject='knowbound-wave4-demo'
if (!(Test-Path -LiteralPath $taskEnvFile)) {
    if ($Action -ne 'Start') { throw 'Demo has not been initialized' }
    New-Item -ItemType Directory -Path (Split-Path $taskEnvFile) -Force | Out-Null
    @('APP_ENV=development','KNOWBOUND_DELIVERY_PROJECT=knowbound-wave4-demo','POSTGRES_DB=wave4_demo','POSTGRES_USER=knowbound',
      ('POSTGRES_PASSWORD='+[Guid]::NewGuid().ToString('N')),('AUTH_TOKEN_SECRET='+[Guid]::NewGuid().ToString('N')+[Guid]::NewGuid().ToString('N')),
      ('DEMO_PASSWORD='+[Guid]::NewGuid().ToString('N')),'API_PORT=8208','WEB_PORT=5209',
      'CORS_ALLOWED_ORIGINS=http://127.0.0.1:5209,http://localhost:5209','MODEL_PROVIDER=disabled','RUNNER_TIMEOUT_SECONDS=15','RUNNER_ENDPOINT=http://runner-controller:8080',
      'RUNNER_SANDBOX_IMAGE=knowbound-wave4-demo-sandbox:task11','DOCKER_GID=0') | Set-Content -LiteralPath $taskEnvFile -Encoding ascii
}
$taskConfig=@{}
foreach($taskLine in Get-Content -LiteralPath $taskEnvFile) {
    if($taskLine -match '^([A-Z0-9_]+)=(.*)$') { $taskConfig[$Matches[1]]=$Matches[2] }
}
foreach($taskPair in @(@('KNOWBOUND_DELIVERY_PROJECT',$taskProject),@('POSTGRES_DB','wave4_demo'),@('POSTGRES_USER','knowbound'),@('APP_ENV','development'),@('API_PORT','8208'),@('WEB_PORT','5209'),@('RUNNER_SANDBOX_IMAGE','knowbound-wave4-demo-sandbox:task11'),@('RUNNER_ENDPOINT','http://runner-controller:8080'),@('MODEL_PROVIDER','disabled'))) {
    if($taskConfig[$taskPair[0]] -ne $taskPair[1]) { throw ('Incompatible demo configuration: '+$taskPair[0]) }
}
foreach($taskKey in @('POSTGRES_PASSWORD','DEMO_PASSWORD')) {
    if($taskConfig[$taskKey] -notmatch '^[a-f0-9]{32}$') { throw ('Explicit generated credential required: '+$taskKey) }
}
foreach($taskKey in $taskConfig.Keys) {
    $taskInherited=[Environment]::GetEnvironmentVariable($taskKey,'Process')
    if($null -ne $taskInherited -and $taskInherited -ne $taskConfig[$taskKey]) { throw ('Inherited environment conflicts with demo configuration: '+$taskKey) }
}
Push-Location -LiteralPath $taskRoot
try {
    $taskIds=@(& docker ps -aq --filter ('name=^/'+$taskProject+'-'))
    if($LASTEXITCODE -ne 0) { throw 'Docker unavailable' }
    foreach($taskId in $taskIds) {
        $taskLabels=(& docker inspect $taskId --format '{{json .Config.Labels}}') | ConvertFrom-Json
        if($LASTEXITCODE -ne 0 -or $taskLabels.'knowbound.task' -ne 'wave4-task11-demo' -or $taskLabels.'com.docker.compose.project' -ne $taskProject) { throw 'Refuse to modify a foreign container' }
    }
    foreach($taskKind in @('volume','network')) {
        $taskResources=@(& docker $taskKind ls -q --filter ('name=^'+$taskProject+'_'))
        if($LASTEXITCODE -ne 0) { throw 'Cannot verify existing demo resources' }
        foreach($taskResource in $taskResources) {
            $taskLabels=(& docker $taskKind inspect $taskResource --format '{{json .Labels}}') | ConvertFrom-Json
            if($LASTEXITCODE -ne 0 -or $taskLabels.'knowbound.task' -ne 'wave4-task11-demo' -or $taskLabels.'com.docker.compose.project' -ne $taskProject) { throw 'Refuse to reuse a foreign persistent resource' }
        }
    }
    $taskCompose=@('compose','--env-file',$taskEnvFile,'-p',$taskProject,'-f','infra/compose/docker-compose.yml','-f','infra/compose/docker-compose.delivery.yml')
    $taskVolumeOverride=Join-Path $taskRoot '.delivery/active-volume.yml'
    if($FreshData) {
        if($Action -ne 'Start') { throw 'FreshData only applies to Start' }
        # Preserve every previous synthetic volume and its failure history.
        $taskVolume='knowbound-wave4-demo_postgres_task11-'+[Guid]::NewGuid().ToString('N')
        @('volumes:','  postgres-data:',('    name: '+$taskVolume)) | Set-Content -LiteralPath $taskVolumeOverride -Encoding ascii
        Write-Output ('Fresh synthetic volume selected: '+$taskVolume)
    }
    if(Test-Path -LiteralPath $taskVolumeOverride) {
        $taskVolumeText=Get-Content -LiteralPath $taskVolumeOverride -Raw
        if($taskVolumeText -notmatch '\Avolumes:\r?\n  postgres-data:\r?\n    name: knowbound-wave4-demo_postgres_task11-[a-f0-9]{32}\r?\n\z') { throw 'Invalid owned volume selection' }
        $taskCompose+=@('-f',$taskVolumeOverride)
    }
    & docker @taskCompose config --quiet
    if($LASTEXITCODE -ne 0) { throw 'Demo Compose configuration invalid' }
    if($Action -eq 'Start') {
        if(!$NoBuild) { & docker @taskCompose build; if($LASTEXITCODE -ne 0) { throw 'Locked demo build failed' } }
        $taskUp=@('up','-d','--no-build','--wait','--wait-timeout','180')
        if($FreshData) { $taskUp+='--force-recreate' }
        & docker @taskCompose @taskUp
        if($LASTEXITCODE -ne 0) { throw 'Demo services did not reach healthy state' }
        Write-Output 'Synthetic demo ready: http://127.0.0.1:5209 ; API http://127.0.0.1:8208'
        Write-Output 'Actors: demo-teacher, demo-student-1 through demo-student-6. Password is in ignored .delivery/demo.env (DEMO_PASSWORD).'
    } elseif($Action -eq 'Stop') {
        & docker @taskCompose stop
        if($LASTEXITCODE -ne 0) { throw 'Demo stop failed' }
    } else {
        & docker @taskCompose ps --all
        if($LASTEXITCODE -ne 0) { throw 'Demo status failed' }
    }
} finally { Pop-Location }

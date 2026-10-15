param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$EvidenceDirectory,
    [switch]$Candidate
)
$ErrorActionPreference='Stop'
$taskRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskEvidence=[IO.Path]::GetFullPath($EvidenceDirectory)
if(Test-Path -LiteralPath $taskEvidence) { throw 'Use a new evidence directory; historical runs must be preserved' }
New-Item -ItemType Directory -Path $taskEvidence | Out-Null
Push-Location -LiteralPath $taskRoot
try {
    $taskHead=(& git rev-parse HEAD).Trim()
    $taskDirty=@(& git status --porcelain --untracked-files=normal)
    if(!$Candidate -and $taskDirty.Count) { throw 'Final verification requires a clean committed worktree' }
    if($env:DATABASE_URL) { throw 'DATABASE_URL must not override isolated regression fixtures' }
    function Record([string]$Name,[string]$Exe,[string[]]$Arguments,[string]$Directory=$taskRoot,[string[]]$Artifacts=@()) {
        & "$PSScriptRoot/record-delivery-command.ps1" -Name $Name -Executable $Exe -CommandArguments $Arguments -WorkingDirectory $Directory -EvidenceDirectory $taskEvidence -ArtifactPaths $Artifacts
    }
    Record 'demo-cold-build-start' 'pwsh' @('-NoProfile','-File',"$PSScriptRoot/start-delivery.ps1",'-FreshData')
    Record 'demo-idempotent-restart' 'pwsh' @('-NoProfile','-File',"$PSScriptRoot/start-delivery.ps1",'-NoBuild')
    Record 'runtime-versions-health' 'pwsh' @('-NoProfile','-File',"$PSScriptRoot/delivery-runtime.ps1")
    Record 'frontend-lock-install' 'npm.cmd' @('ci') "$taskRoot/frontend"
    $env:DELIVERY_BROWSER_EVIDENCE=Join-Path $taskEvidence 'delivery-browser'
    Record 'delivery-browser-15-steps' 'npx.cmd' @('playwright','test','--config','playwright.delivery.config.ts') "$taskRoot/frontend"
    $taskRehearsals=@(Get-ChildItem -LiteralPath $env:DELIVERY_BROWSER_EVIDENCE -Filter rehearsal.json -Recurse -File)
    if($taskRehearsals.Count -ne 1) { throw 'Exactly one actual rehearsal report required' }
    Record 'delivery-readonly-sql' 'pwsh' @('-NoProfile','-File',"$PSScriptRoot/probe-delivery.ps1",'-RehearsalPath',$taskRehearsals[0].FullName,'-OutputPath',"$taskEvidence/delivery-sql.json") $taskRoot @("$taskEvidence/delivery-sql.json")

    # Only dedicated Task 11 resources may be started or reused.
    $taskProject='knowbound-wave4-test'
    $taskIds=@(& docker ps -aq --filter ('name=^/'+$taskProject+'-'))
    if($LASTEXITCODE -ne 0) { throw 'Docker unavailable' }
    foreach($taskId in $taskIds) {
        $taskLabels=(& docker inspect $taskId --format '{{json .Config.Labels}}') | ConvertFrom-Json
        if($LASTEXITCODE -ne 0 -or $taskLabels.'com.docker.compose.project' -ne $taskProject -or $taskLabels.'knowbound.task' -ne 'wave4-task11-test') { throw 'Refuse foreign regression container' }
    }
    foreach($taskKind in @('volume','network')) {
        foreach($taskResource in @(& docker $taskKind ls -q --filter ('name=^'+$taskProject+'_task11-'))) {
            $taskLabels=(& docker $taskKind inspect $taskResource --format '{{json .Labels}}') | ConvertFrom-Json
            if($LASTEXITCODE -ne 0 -or $taskLabels.'com.docker.compose.project' -ne $taskProject -or $taskLabels.'knowbound.task' -ne 'wave4-task11-test') { throw 'Refuse foreign regression persistent resource' }
        }
    }
    $taskTestEnv=Join-Path $taskRoot '.superpowers/sdd/2026-10-12-wave4-task11-delivery/test.env'
    if(!(Test-Path -LiteralPath $taskTestEnv)) {
        New-Item -ItemType Directory -Path (Split-Path $taskTestEnv) -Force | Out-Null
        @('APP_ENV=test','POSTGRES_USER=knowbound','POSTGRES_DB=knowbound',('POSTGRES_PASSWORD='+[Guid]::NewGuid().ToString('N')),
          'RUNNER_SANDBOX_IMAGE=knowbound-wave4-test-sandbox:task11','WAVE4_CONTROLLER_IMAGE=knowbound-wave4-demo-controller:task11','DOCKER_GID=0') | Set-Content -LiteralPath $taskTestEnv -Encoding ascii
    }
    Record 'test-sandbox-image' 'docker' @('tag','knowbound-wave4-demo-sandbox:task11','knowbound-wave4-test-sandbox:task11')
    $taskCompose=@('compose','--env-file',$taskTestEnv,'-p',$taskProject,'-f','infra/compose/docker-compose.yml','-f','infra/compose/docker-compose.wave4-test.yml')
    Record 'test-compose-config' 'docker' ($taskCompose+@('config','--quiet'))
    Record 'test-services' 'docker' ($taskCompose+@('up','-d','--no-build','--force-recreate','--wait','--wait-timeout','180','postgres','runner-sandbox','runner-controller'))
    Record 'test-environment-prepare' 'pwsh' @('-NoProfile','-File',"$PSScriptRoot/use-delivery-test-environment.ps1",'-Python',$Python)
    & "$PSScriptRoot/use-delivery-test-environment.ps1" -Python $Python
    Record 'backend-full' $Python @('-B','-m','pytest','tests','-q','-p','no:cacheprovider','-o','junit_family=legacy',"--basetemp=$taskEvidence/backend-temp","--junitxml=$taskEvidence/backend.xml") "$taskRoot/backend"
    Record 'runtime-openapi' $Python @('-B','-m','pytest','tests/contracts/test_wave3_runtime_openapi.py','-q','-p','no:cacheprovider',"--basetemp=$taskEvidence/openapi-temp") "$taskRoot/backend"
    Record 'frontend-components' 'npm.cmd' @('test') "$taskRoot/frontend"
    Record 'frontend-types-build' 'npm.cmd' @('run','build') "$taskRoot/frontend"
    $env:DEFAULT_BROWSER_EVIDENCE=Join-Path $taskEvidence 'default-browser'
    $env:GATE_BROWSER_EVIDENCE=Join-Path $taskEvidence 'gate-browser'
    Record 'default-browser' 'npx.cmd' @('playwright','test') "$taskRoot/frontend"
    Record 'gate-browser' 'npx.cmd' @('playwright','test','--config','playwright.gate.config.ts') "$taskRoot/frontend"
    Record 'gate-readonly-sql' $Python @('-B','-m','tests.integration.wave3_browser_sql_probe') "$taskRoot/backend"

    $taskContext=Join-Path $taskRoot ('.superpowers/sdd/2026-10-12-wave4-task11-delivery/test-images-'+[Guid]::NewGuid().ToString('N'))
    Record 'runner-test-tools' $Python @('-B',"$PSScriptRoot/prepare-runner-tests.py",$taskContext)
    foreach($taskKind in @('worker','controller')) {
        $taskBase=if($taskKind -eq 'worker'){'knowbound-wave4-test-sandbox:task11'}else{'knowbound-wave4-demo-controller:task11'}
        $taskBaseId=(& docker image inspect $taskBase --format '{{.Id}}').Trim()
        if($LASTEXITCODE -ne 0) { throw 'Current built base image missing' }
        $taskBaseMetadata=Join-Path $taskEvidence ('runner-'+$taskKind+'-base.json')
        @{head=$taskHead;local_image=$taskBase;immutable_id=$taskBaseId;pull=$false} | ConvertTo-Json | Set-Content -LiteralPath $taskBaseMetadata -Encoding utf8
        Record ('runner-'+$taskKind+'-test-build') 'docker' @('build','--pull=false','--build-arg',('BASE_IMAGE='+$taskBase),'-t',('knowbound-wave4-'+$taskKind+'-tests:task11'),$taskContext) $taskRoot @($taskBaseMetadata)
        if((& docker image inspect $taskBase --format '{{.Id}}').Trim() -ne $taskBaseId) { throw 'Local immutable test base changed during build' }
    }
    $taskLimits=@('run','--rm','--network','none','--read-only','--user','10001:10001','--cap-drop','ALL','--security-opt','no-new-privileges:true','--pids-limit','64','--memory','512m','--cpus','1','--tmpfs','/work:rw,nosuid,nodev,exec,size=64m,mode=0700,uid=10001,gid=10001')
    Record 'worker-31-isolated' 'docker' ($taskLimits+@('knowbound-wave4-worker-tests:task11','/app/runner/tests/test_executor.py','/app/runner/tests/test_parser.py','/app/runner/tests/test_cli.py','/app/runner/tests/test_protocol.py','-q','-p','no:cacheprovider','--basetemp=/work/pytest-temp'))
    Record 'controller-12-isolated' 'docker' ($taskLimits+@('knowbound-wave4-controller-tests:task11','/app/runner/tests/test_controller.py','/app/runner/tests/test_docker_engine.py','-q','-p','no:cacheprovider','--basetemp=/work/pytest-temp'))
    $env:TASK11_STABILITY_EVIDENCE=$taskEvidence
    Record 'runner-topology-and-stability' $Python @('-B','-m','pytest','runner/tests/test_wave3_isolated_topology.py','runner/tests/test_wave4_stability.py','-q','-p','no:cacheprovider','-o','junit_family=legacy',"--basetemp=$taskEvidence/runner-temp","--junitxml=$taskEvidence/runner.xml")
    Record 'evaluation-structure' $Python @('-B','data/evaluation/evaluate.py')
    Record 'historical-manifest-preserved' $Python @('-B','data/evaluation/map_security_execution.py')
    $taskBackendRecord=@(Get-ChildItem -LiteralPath $taskEvidence -Directory -Filter 'backend-full-*' | ForEach-Object { Join-Path $_.FullName 'command.json' })
    if($taskBackendRecord.Count -ne 1) { throw 'Backend command record ambiguous' }
    $taskMapping=@('-B','data/evaluation/map_delivery_execution.py','--report',"$taskEvidence/backend.xml",'--command',$taskBackendRecord[0],'--head',$taskHead,'--output',"$taskEvidence/security-execution-manifest.json")
    if($Candidate) { $taskMapping+='--allow-dirty-candidate' }
    Record 'task11-security-manifest' $Python $taskMapping $taskRoot @("$taskEvidence/security-execution-manifest.json")
    Record 'git-diff-check' 'git' @('diff','--check')
    Record 'git-unresolved-check' 'git' @('ls-files','-u')
    $taskFinalDirty=@(& git status --porcelain --untracked-files=normal)
    if(!$Candidate -and $taskFinalDirty.Count) { throw 'Worktree changed during final verification' }
    & $Python -B "$PSScriptRoot/summarize-delivery.py" $taskEvidence $taskHead $(if($Candidate){'candidate'}else{'final'})
    if($LASTEXITCODE -ne 0) { throw 'Evidence integrity or completeness failed' }
    Write-Output ('Verification evidence: '+$taskEvidence)
} finally { Pop-Location }

param([Parameter(Mandatory=$true)][string[]]$AllowedEmail, [switch]$FreshData)
$ErrorActionPreference='Stop'
# A named email is required; never fall back to anonymous or domain-wide access.
foreach($taskMail in $AllowedEmail) {
    if($taskMail -match '[*?,;\s]' -or $taskMail -notmatch '^[^@]+@[^@]+\.[^@]+$') { throw 'Use individual teacher email addresses; no wildcards or lists inside one value' }
    try { $taskParsed=[System.Net.Mail.MailAddress]::new($taskMail) } catch { throw 'Invalid teacher email address' }
    if($taskParsed.Address -cne $taskMail) { throw 'Use a plain teacher email address' }
}
if($AllowedEmail.Count -eq 0) { throw 'At least one teacher email is required' }
$taskCloudflared=Get-Command cloudflared -ErrorAction SilentlyContinue
if(!$taskCloudflared) { throw 'Install cloudflared with --allowed-mail support first; see docs/teacher-test.md' }
if(!(Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker Desktop with the Linux engine is required' }
# Windows PowerShell 5.1 turns redirected native stderr into a terminating error under Stop.
$ErrorActionPreference='Continue'
$taskHelp=(& $taskCloudflared.Source tunnel --help 2>&1 | Out-String)
$taskHelpExit=$LASTEXITCODE
$ErrorActionPreference='Stop'
if($taskHelpExit -ne 0 -or $taskHelp -notmatch '--allowed-mail') { throw 'This cloudflared cannot protect access by email; update it before starting' }

& (Join-Path $PSScriptRoot 'start-delivery.ps1') -TeacherTest -FreshData:$FreshData
if(!$? -or $LASTEXITCODE -ne 0) { throw 'Teacher test services failed to start' }
# Verify both routes before creating an external URL. No credentials in output.
$taskPage=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5209/' -TimeoutSec 10
$taskHealth=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5209/api/health' -TimeoutSec 10
if($taskPage.StatusCode -ne 200 -or $taskHealth.StatusCode -ne 200 -or $taskHealth.Headers.'Content-Type' -notmatch 'application/json') { throw 'The same-origin Web/API entry is not ready' }
$taskArgs=@('tunnel','--url','http://127.0.0.1:5209')
foreach($taskMail in ($AllowedEmail | Select-Object -Unique)) { $taskArgs+=@('--allowed-mail',$taskMail) }
Write-Output 'Share only the HTTPS URL printed below. Teachers need email verification AND an application account.'
Write-Output 'Synthetic data and deterministic model Mock; compilation uses the real isolated Runner.'
Write-Output 'Keep this terminal open. Press Ctrl+C to close public access. Local services remain running.'
& $taskCloudflared.Source @taskArgs
if($LASTEXITCODE -ne 0) { throw 'Tunnel stopped with an error; public access has ended' }

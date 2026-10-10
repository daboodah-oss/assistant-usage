<#
.SYNOPSIS
  Register (or remove) the Windows scheduled task that samples Claude usage
  every 15 minutes.  Run once from a normal (non-admin) PowerShell:

    cd <your clone of assistant-usage>
    .\lanes\claude\install-task.ps1

  Remove it again with:  .\lanes\claude\install-task.ps1 -Uninstall

.DESCRIPTION
  The task runs lanes\claude\run.ps1 hidden in your logged-on session, on
  battery too, and catches up if the PC was asleep.  It requires PowerShell 7
  (pwsh).  Nothing here touches tokens.
#>
param(
    [string]$RepoPath = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$ConfigDir = (Join-Path $env:USERPROFILE ".claude-sampler"),
    [switch]$Uninstall
)
$ErrorActionPreference = "Stop"
$taskName = "assistant-usage claude lane"

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task '$taskName'."
    exit 0
}

# ---- preflight -----------------------------------------------------------
$pwsh = (Get-Command pwsh -ErrorAction SilentlyContinue)?.Source
if (-not $pwsh) { throw "PowerShell 7 (pwsh) not found.  Install with: winget install Microsoft.PowerShell" }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "git not found on PATH" }
if (-not ((Get-Command python -ErrorAction SilentlyContinue) -or (Get-Command py -ErrorAction SilentlyContinue))) { throw "python not found on PATH" }
if (-not (Test-Path (Join-Path $RepoPath ".git"))) { throw "No git repo at $RepoPath (pass -RepoPath)" }

$cred = Join-Path $ConfigDir ".credentials.json"
if (-not (Test-Path $cred)) {
    Write-Host ""
    Write-Host "No sampler login yet at $cred" -ForegroundColor Yellow
    Write-Host "Create one (a separate login just for the sampler), then re-run this script:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "    `$env:CLAUDE_CONFIG_DIR = `"$ConfigDir`"; claude login" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Do that in a throwaway PowerShell window and close it afterwards, so your"
    Write-Host "normal Claude Code keeps using its own login in %USERPROFILE%\.claude."
    exit 1
}

# ---- register -------------------------------------------------------------
$runner = Join-Path $PSScriptRoot "run.ps1"
$action = New-ScheduledTaskAction -Execute $pwsh `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runner`" -RepoPath `"$RepoPath`" -ConfigDir `"$ConfigDir`""

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 15)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -RunOnlyIfNetworkAvailable
# Interactive: runs in your logged-on session, so git can reach the HTTPS
# credential that Git Credential Manager keeps for you.  (A "whether logged on
# or not" task cannot unlock that store, so pushes would fail.)  Samples pause
# while you are logged out or the PC sleeps; the page shows the gap honestly.
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "Registered scheduled task '$taskName' (every 15 min)."

# ---- first run now, show the result ----------------------------------------
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 20
$log = Join-Path $env:LOCALAPPDATA "assistant-usage\claude-lane.log"
Write-Host ""
Write-Host "Last log lines ($log):"
Get-Content $log -Tail 4 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  $_" }
Write-Host ""
Write-Host "Expect 'collect: claude-collector: status=ok ...' followed by 'pushed'."
Write-Host "If the status says relogin_needed, redo the claude login command above."

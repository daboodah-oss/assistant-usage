<#
.SYNOPSIS
  Re-provision the Claude lane's own login (README: "Re-provisioning the login").
  Run it from any PowerShell window, or right-click > Run with PowerShell:

    & "$env:USERPROFILE\github\assistant-usage-sampler\lanes\claude\relogin.ps1"

.DESCRIPTION
  Signs the sampler's dedicated config dir (%USERPROFILE%\.claude-sampler) in
  again with `claude auth login --claudeai`.  The flag picks "Claude
  subscription" up front, so there is no menu to arrow through (arrow keys may
  not reach it over remote desktop).  Only the browser sign-in is left to do.

  CLAUDE_CONFIG_DIR is set for the login only and put back afterwards, so your
  normal Claude Code login in %USERPROFILE%\.claude is untouched.  Afterwards it
  prints the new expiry date (never a token) and runs one sampling cycle.

  Works in Windows PowerShell 5.1 and PowerShell 7.
#>
param(
    [string]$ConfigDir = (Join-Path $env:USERPROFILE ".claude-sampler"),
    [switch]$NoPause
)
$ErrorActionPreference = "Stop"
$taskName = "assistant-usage claude lane"
$cred = Join-Path $ConfigDir ".credentials.json"

function Show-Expiry {
    if (-not (Test-Path $cred)) { Write-Host "No credentials file at $cred" -ForegroundColor Yellow; return $null }
    $o = (Get-Content $cred -Raw | ConvertFrom-Json).claudeAiOauth
    if (-not $o.refreshTokenExpiresAt) { Write-Host "Login present; expiry date not recorded."; return $null }
    $exp = [DateTimeOffset]::FromUnixTimeMilliseconds([int64]$o.refreshTokenExpiresAt).LocalDateTime
    $days = ($exp - (Get-Date)).TotalDays
    Write-Host ("Sampler login expires {0:ddd MMM d, h:mm tt} ({1:0.#} days from now), plan {2}." -f $exp, $days, $o.subscriptionType)
    return $exp
}

function Done([int]$code) {
    if (-not $NoPause) { Write-Host ""; Read-Host "Press Enter to close" | Out-Null }
    exit $code
}

if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Host "Claude Code ('claude') is not on PATH." -ForegroundColor Red
    Done 1
}

Write-Host "Current state:"
$before = Show-Expiry
Write-Host ""
Write-Host "Starting sign-in for the SAMPLER's login ($ConfigDir)."
Write-Host "Finish it in the browser.  If no browser opens, copy the link shown below into one;"
Write-Host "if the page gives you a code, paste it here and press Enter."
Write-Host ""

$saved = $env:CLAUDE_CONFIG_DIR
try {
    $env:CLAUDE_CONFIG_DIR = $ConfigDir
    & claude auth login --claudeai
    $rc = $LASTEXITCODE
}
finally {
    $env:CLAUDE_CONFIG_DIR = $saved
}

Write-Host ""
$after = Show-Expiry
if ($rc -ne 0 -or $null -eq $after -or ($null -ne $before -and $after -le $before)) {
    Write-Host "Sign-in did not produce a new login (exit code $rc).  Try again." -ForegroundColor Red
    Done 1
}
Write-Host "New login saved." -ForegroundColor Green

# One cycle now, so the dashboard picks up again without waiting for the next quarter-hour.
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Write-Host "Running one sampling cycle..."
    Start-ScheduledTask -TaskName $taskName
    Start-Sleep -Seconds 20
    $log = Join-Path $env:LOCALAPPDATA "assistant-usage\claude-lane.log"
    Get-Content $log -Tail 3 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  $_" }
    Write-Host "Expect 'status=ok' then 'pushed'."
} else {
    Write-Host "Scheduled task '$taskName' not found; run install-task.ps1." -ForegroundColor Yellow
}
Done 0

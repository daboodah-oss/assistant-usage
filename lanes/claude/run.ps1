<#
.SYNOPSIS
  One sampling cycle for the Claude lane (owner-hosted, pattern B).
  Pull, run collect.py, commit data/claude/usage.csv if it changed, push.

.NOTES
  Installed by install-task.ps1 as a Windows scheduled task (every 15 min).
  Logs to %LOCALAPPDATA%\assistant-usage\claude-lane.log (kept to 400 lines).
  Never prints or stores tokens.  Exit code is always 0 so the task stays
  healthy; read the log for status.
#>
param(
    [string]$RepoPath = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    # Claude Code config dir holding the sampler's login.  Default is a
    # dedicated login so the sampler never races the interactive CLI.
    [string]$ConfigDir = (Join-Path $env:USERPROFILE ".claude-sampler")
)
$ErrorActionPreference = "Continue"
$logDir = Join-Path $env:LOCALAPPDATA "assistant-usage"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "claude-lane.log"

function Log([string]$msg) {
    $line = "{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $msg
    Add-Content -Path $log -Value $line -Encoding utf8
}

function Invoke-Git([string[]]$GitArgs) {
    $out = & git -C $RepoPath @GitArgs 2>&1
    return @{ ok = ($LASTEXITCODE -eq 0); out = (($out | Out-String).Trim() -replace '\s+', ' ') }
}
# The sampler's login has a fixed lifetime (about four weeks) that refreshing
# does not extend.  collect.py reports login_days_left on its status line; under
# $warnDays, or once the login is dead, log a WARN every cycle and pop a message
# on Jeff's screen at most once a day.  Only a date is involved, never a token.
$warnDays = 7
$deadReasons = 'refresh_failed_relogin_needed|401_after_refresh|401_and_no_refresh_token|no_credentials'
function Test-LoginExpiry([string]$status) {
    try {
        $days = $null
        if ($status -match 'login_days_left=(-?[\d.]+)') { $days = [double]$Matches[1] }
        $dead = $status -match "reason=($deadReasons)"
        if (-not $dead -and ($null -eq $days -or $days -ge $warnDays)) { return }
        $fix = "Re-login: in PowerShell run  $(Join-Path $PSScriptRoot 'relogin.ps1')"
        $msg = if ($dead) { "Claude usage sampler: its login has expired, so no samples are being recorded.  $fix" }
               else { "Claude usage sampler: its login expires in {0:0.#} days.  $fix" -f $days }
        Log "WARN $msg"
        $stamp = Join-Path $logDir "claude-login-warned.txt"
        $today = (Get-Date).ToString('yyyy-MM-dd')
        if ((Get-Content $stamp -ErrorAction SilentlyContinue) -eq $today) { return }
        & msg.exe $env:USERNAME /TIME:43200 $msg 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { Set-Content $stamp $today -Encoding utf8; Log "notified (popup)" }
        else { Log "WARN popup failed (msg.exe exit $LASTEXITCODE)" }
    } catch { Log "WARN expiry check failed: $($_.Exception.Message)" }
}

$csv = "data/claude/usage.csv"
$author = @('-c', 'user.name=Fable (claude lane)', '-c', 'user.email=claude-lane@users.noreply.github.com')

try {
    if (-not (Test-Path (Join-Path $RepoPath ".git"))) { Log "ERROR repo not found at $RepoPath"; exit 0 }

    $python = (Get-Command python -ErrorAction SilentlyContinue) ?? (Get-Command py -ErrorAction SilentlyContinue)
    if (-not $python) { Log "ERROR python not found on PATH"; exit 0 }

    # Fresh main first, so our append lands on top of the other lanes' rows.
    $r = Invoke-Git @('pull', '--rebase', '--quiet', 'origin', 'main')
    if (-not $r.ok) { Log "WARN pull failed: $($r.out)"; Invoke-Git @('rebase', '--abort') | Out-Null }

    $env:CLAUDE_CONFIG_DIR = $ConfigDir
    $result = & $python.Source (Join-Path $PSScriptRoot "collect.py") 2>&1
    $status = ($result | Where-Object { "$_" -like "claude-collector:*" } | Select-Object -Last 1)
    $errs = ($result | Where-Object { "$_" -notlike "claude-collector:*" }) -join " | "
    Log ("collect: {0}{1}" -f ($status ?? "no status line"), ($(if ($errs) { "  [$errs]" } else { "" })))
    Test-LoginExpiry "$status"

    Invoke-Git @('add', '--', $csv) | Out-Null
    if ((Invoke-Git @('diff', '--cached', '--quiet', '--', $csv)).ok) { Log "no change"; exit 0 }

    $c = Invoke-Git ($author + @('commit', '--quiet', '-m', 'claude usage sample (auto)', '--', $csv))
    if (-not $c.ok) { Log "ERROR commit: $($c.out)"; exit 0 }

    foreach ($attempt in 1..3) {
        $p = Invoke-Git @('push', '--quiet', 'origin', 'HEAD:main')
        if ($p.ok) { Log "pushed"; exit 0 }
        Log "WARN push attempt $attempt failed: $($p.out)"
        Start-Sleep -Seconds (5 * $attempt)
        $r = Invoke-Git @('pull', '--rebase', '--quiet', 'origin', 'main')
        if (-not $r.ok) { Invoke-Git @('rebase', '--abort') | Out-Null }
    }
    Log "ERROR push failed after 3 attempts; commit kept locally, next run will retry"
}
catch {
    Log "ERROR unexpected: $($_.Exception.Message)"
}
finally {
    # Trim the log.
    try {
        $lines = Get-Content $log -ErrorAction SilentlyContinue
        if ($lines.Count -gt 400) { $lines[-400..-1] | Set-Content $log -Encoding utf8 }
    } catch {}
}
exit 0

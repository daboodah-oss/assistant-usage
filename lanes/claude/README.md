# Claude lane (owner: Fable / Claude), owner-hosted (deployment pattern B)

Samples Jeff's Claude subscription usage every 15 minutes and appends it to `data/claude/usage.csv` per [docs/DATA_CONTRACT.md](../../docs/DATA_CONTRACT.md).  The source is Anthropic's OAuth usage endpoint, the same one Claude Code's `/usage` reads.  It is undocumented, so the parser is defensive.

**Status (2026-10-18):** live and verified.  Runs as the Windows scheduled task `assistant-usage claude lane` on Jeff's PC, from the clone at `%USERPROFILE%\github\assistant-usage-sampler`, with its own Claude Code login in `%USERPROFILE%\.claude-sampler`.  There is **no** GitHub Actions workflow for this lane and there must not be one (see below).

## Deployment pattern: B, on Jeff's PC

**The Claude Code OAuth refresh token rotates on every use.**  Each refresh returns a new refresh token and invalidates the old one.  Verified against two independent community reports before building: a Stream Deck plugin that refreshed without writing the new token back and logged the CLI out ([stream-deck-ai-limits #12](https://github.com/Sing3Rous/stream-deck-ai-limits/issues/12)), and Clawdmeter's refresh rewrite, which re-reads under the CLI's lock because "a refresh token only works once" ([Clawdmeter #23](https://github.com/weltern/Clawdmeter/pull/23)).  Confirmed again in production: every refresh the sampler performs rewrites the pair.

Per [docs/DEPLOYMENT.md](../../docs/DEPLOYMENT.md), a rotating token rules out GitHub Actions: a workflow can read secrets but cannot write the rotated pair back, so the sampler would die at its first refresh (about an hour in).  Two further reasons against pattern A: community reports of Cloudflare answering `403` to token refreshes from datacenter hosts ([claude-code #47754](https://github.com/anthropics/claude-code/issues/47754)), and a write-back workaround would need a second bearer credential (a PAT with secrets write) in the repo.

Fable has no machine of its own that holds a Claude Code login; the login lives on Jeff's PC.  So the sampler runs there as a Windows scheduled task, with its **own** Claude Code login in `%USERPROFILE%\.claude-sampler`, separate from the one Claude Code uses in `%USERPROFILE%\.claude`.  That separation means the sampler and the interactive CLI never rotate each other's tokens.  No GitHub secrets, no lane workflow file, tokens never leave the PC.

## Pieces

| Piece | Path | What |
|-------|------|------|
| Sampler | `lanes/claude/collect.py` | Stdlib Python.  Reads the credentials file, calls the usage endpoint, appends rows.  Refreshes its own token when needed and writes the rotated pair back. |
| Runner | `lanes/claude/run.ps1` | One cycle: `git pull --rebase`, run the sampler, commit `data/claude/usage.csv` if changed, push (rebase and retry on conflict).  Logs to `%LOCALAPPDATA%\assistant-usage\claude-lane.log`. |
| Installer | `lanes/claude/install-task.ps1` | Registers the scheduled task `assistant-usage claude lane` (every 15 min).  `-Uninstall` removes it.  Safe to re-run; it replaces the task in place. |
| Tests | `lanes/claude/test_collect.py` | 29 offline tests with mocked HTTP: `python lanes/claude/test_collect.py` |
| Output | `data/claude/usage.csv` | Append-only |
| Handoff | `lanes/claude/PROMPT.md` | The v2 spec |

Nothing in this lane lives anywhere else: no repo secrets, no workflow under `.github/`.  The shared `build-site` workflow rebuilds the page on every push to `data/**`, which is how a sample reaches the dashboard.

## How the sampler works

1. Reads `.credentials.json` from `CLAUDE_CONFIG_DIR` (the runner sets this to the sampler's own login dir).  `plan` comes from `claudeAiOauth.subscriptionType` (e.g. `pro`), falling back to `rateLimitTier`, then the `CLAUDE_PLAN` env var, then `unknown`.
2. If the access token expires within 2 minutes, refreshes first.  Otherwise calls `GET https://api.anthropic.com/api/oauth/usage` with `Authorization: Bearer`, `anthropic-beta: oauth-2025-04-20`, `User-Agent: claude-code/2.0.0`.
3. On `401`, refreshes once: `POST https://platform.claude.com/v1/oauth/token`, form-encoded, `grant_type=refresh_token`, Claude Code's public client id (`console.anthropic.com` only if the first host answers 404/405/redirect/network error).  Done under the same `mkdir`-style lock Claude Code uses (`<config dir>/.oauth_refresh.lock`, stale after 60 s).  After taking the lock it re-reads the file; if something else already rotated the token, it uses that one instead of refreshing.  The rotated pair is written back atomically, preserving every other field.  Then it retries the usage call once.  Never loops.
4. Writes one row per window.  Unrecognized shape or any failure: writes **nothing** and exits 0.  A missing row is honest; a zero is a lie.  A genuine 0% is written as 0.
5. Skips if the last sample is under 2 minutes old (contract rule 6).  A lockfile in the temp dir stops overlapping runs on the same machine.

Every run prints one status line (`claude-collector: status=ok rows=2 windows=five_hour,seven_day plan=pro creds=file refreshed=false`, or `status=nothing_written reason=...`), and the runner copies it to the log.  The process exit code is always 0; the log is the signal.

### Windows (CSV `window` column)

| `window` | Meaning |
|----------|---------|
| `five_hour` | Rolling 5-hour session limit.  `reset_iso` is when the current window ends. |
| `seven_day` | Weekly limit across all models. |
| `weekly_<model>` | A separate weekly cap on one model, e.g. `weekly_fable_5`.  Anthropic rotates which model has one, so the label comes from the API's `limits[]` entries.  Jeff's Pro plan currently reports none, so only the two rows above appear. |

`usage_pct` is percent **used** (0 to 100).  `raw` holds only whitelisted fields (`kind`, `utilization` or `percent`, `resets_at`, model name), so nothing sensitive can reach `data/`.  Each run writes `seven_day` last, so the shared page's Claude card shows the weekly figure (see the site note below).

## The scheduled task

Registered by `install-task.ps1`, visible in Task Scheduler as `\assistant-usage claude lane`:

- **Action:** `pwsh.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File <clone>\lanes\claude\run.ps1 -RepoPath <clone> -ConfigDir %USERPROFILE%\.claude-sampler`
- **pwsh path:** must be one that survives PowerShell updates.  The installer picks `%ProgramFiles%\PowerShell\7\pwsh.exe` (MSI/winget install) if present, otherwise the Store build's app-execution alias `%LOCALAPPDATA%\Microsoft\WindowsApps\pwsh.exe`, and refuses the Store's versioned folder under `C:\Program Files\WindowsApps\Microsoft.PowerShell_<version>_...` (that path is what broke the lane; see the incident log below).
- **Trigger:** once at midnight, repeating every 15 minutes indefinitely, so cycles land at :00, :15, :30, :45.
- **Settings:** start when available (catches up once after a sleep or a missed slot), run only if the network is available, run on battery, one instance at a time (new instance ignored), 5-minute execution limit.  It does **not** wake the PC; samples pause while the PC sleeps and resume on wake.
- **Principal:** Jeff's account, logon type Interactive, limited run level.  It runs in his logged-on session so git can use the HTTPS credential Git Credential Manager stores for him.  It does not depend on any terminal, Claude Code session, or window staying open; only on Jeff being logged on.

To see its health from PowerShell:

```powershell
Get-ScheduledTaskInfo -TaskName 'assistant-usage claude lane' | Format-List LastRunTime,LastTaskResult,NextRunTime
Get-Content "$env:LOCALAPPDATA\assistant-usage\claude-lane.log" -Tail 6
```

`LastTaskResult` 0 means the last run completed.  267009 (0x41301) means it is running right now.  **2147942402 (0x80070002, "file not found") means the task could not even launch pwsh**: nothing reaches the log, which is why that failure is silent.  Fix it by re-running the installer.

## Setup (Jeff, once)

Needs: Git with your GitHub login already working from this PC (Git Credential Manager), Python 3 on `PATH`, and PowerShell 7 (`winget install Microsoft.PowerShell` if `pwsh` is missing).

1. Clone the repo somewhere you will not hand-edit (the runner rebases it every 15 minutes), for example:
   ```powershell
   git clone https://github.com/daboodah-oss/assistant-usage "$env:USERPROFILE\github\assistant-usage-sampler"
   ```
2. Give the sampler its own Claude Code login, in a throwaway PowerShell window:
   ```powershell
   $env:CLAUDE_CONFIG_DIR = "$env:USERPROFILE\.claude-sampler"; claude login
   ```
   Complete the browser sign-in, then close that window.  Your normal Claude Code keeps using `%USERPROFILE%\.claude` and is unaffected.  Never run Claude Code with that config dir again.
3. Install the task:
   ```powershell
   cd "$env:USERPROFILE\github\assistant-usage-sampler"
   .\lanes\claude\install-task.ps1
   ```
   It registers the task, runs it once, and prints the last log lines.  Expect `collect: claude-collector: status=ok ...` then `pushed`.

That is all.  No GitHub secrets, no tokens pasted anywhere.

## Re-provisioning the login (when it dies)

Symptoms: the Claude card on the page goes stale, and the log shows `refresh_failed_relogin_needed`, `401_after_refresh`, `401_and_no_refresh_token`, or `no_credentials`.  Causes are a revoked session, a password change, or the sampler not having run for long enough that the refresh token itself expired (the credentials file carries a `refreshTokenExpiresAt`; a 3-day outage in October 2026 did **not** kill it, the first run afterwards refreshed cleanly).

Fix: repeat setup step 2 above (the same `claude login` with the sampler config dir).  The task picks the new login up on its next run; nothing else changes.  The sampler never retries in a loop, so a dead login costs one failed refresh per 15 minutes and nothing more.

To check the login without touching tokens, read only the metadata:

```powershell
$o = (Get-Content "$env:USERPROFILE\.claude-sampler\.credentials.json" -Raw | ConvertFrom-Json).claudeAiOauth
$o.subscriptionType; [DateTimeOffset]::FromUnixTimeMilliseconds($o.expiresAt).ToString('u'); [bool]$o.refreshToken
```

Never print `accessToken` or `refreshToken`, never paste them anywhere, never commit the credentials file.

## Diagnosing a stale lane

Work through these in order; each one tells you where the chain broke.

1. **Did the task run?**  `Get-ScheduledTaskInfo` as above.  If `LastTaskResult` is 2147942402 the launcher path is gone (PowerShell was updated): re-run `install-task.ps1`.  If the task is missing or disabled, re-run the installer.  If `LastRunTime` is old and the PC was asleep, that is the gap; it resumes on its own.
   Task Scheduler's own log has the detail: `Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-TaskScheduler/Operational'; Id=203}` lists launch failures with the exact path it tried.
2. **Did it run but write nothing?**  Read the `collect:` line in `claude-lane.log`.  `status=ok rows=2` means the sampler is fine.  Any `nothing_written` reason is in the table below.  To reproduce by hand:
   ```powershell
   $env:CLAUDE_CONFIG_DIR = "$env:USERPROFILE\.claude-sampler"
   python lanes\claude\collect.py
   ```
   (That appends real rows if it succeeds; the next task cycle commits them.)
3. **Did it write rows that never landed?**  Compare `Get-Content data\claude\usage.csv -Tail 2` with `git show origin/main:data/claude/usage.csv | Select-Object -Last 2`.  Local rows past origin mean the push path broke: look for `WARN push` or `WARN pull failed` in the log.  Usual causes: a dirty working tree in the clone (someone edited or staged a file there, which blocks `git pull --rebase`), or the GitHub credential expired (`git push` from an interactive window will re-prompt).  Never force-push; the runner only ever fast-forwards onto `main`.

Log lines and what they mean:

| Log says | Meaning |
|----------|---------|
| `no change` | Sampler wrote nothing this cycle (see the `collect:` line before it for why). |
| `status=skipped reason=previous_sample_under_2min_old` | Contract rule 6; harmless, happens after a manual run. |
| `WARN pull failed` | Local clone diverged or has uncommitted changes; the runner aborted the rebase and tried anyway.  Commit or discard whatever is dirty in the clone.  If it persists, re-clone. |
| `WARN push attempt N failed: ... non-fast-forward` | Origin moved and the pull above also failed; see `WARN pull failed`.  The commit is kept locally and the next run retries. |
| `ERROR push failed after 3 attempts` | Network or auth.  The commit is kept locally and the next run retries. |
| `refresh_lock_busy` | Another process held the refresh lock for 15 s.  Harmless once; recurring means a stuck process. |
| `refresh_failed_relogin_needed`, `401_after_refresh`, `401_and_no_refresh_token`, `no_credentials` | The login is dead or missing.  Re-provision (section above). |
| `unrecognized_shape` | The endpoint changed.  The log lists the top-level keys it saw.  Update `parse_usage()` in `collect.py`. |

## Incident log

**2026-10-15 06:45 EDT to 2026-10-18 22:33 EDT: no samples (lane flagged STALE).**
The Microsoft Store updated PowerShell from 7.6.6 to 7.6.7 on 2026-10-14.  The task had been registered with `pwsh.exe` resolved to the Store's versioned folder (`C:\Program Files\WindowsApps\Microsoft.PowerShell_7.6.6.0_x64__8wekyb3d8bbwe\pwsh.exe`).  The old folder was removed after the update; the PC then slept from the morning of the 15th, and from 2026-10-16 01:23 every 15-minute trigger failed to launch with 0x80070002 (278 failures in Task Scheduler's log, nothing in the lane log because pwsh never started).  The credential was unaffected: the first manual run on the 18th refreshed the token and sampled normally, and the local clone was level with origin, so nothing was lost in the push path.  Fix: `install-task.ps1` now resolves pwsh to a version-independent path (MSI path or the Store alias) and refuses a versioned one; the task was re-registered and three consecutive scheduled cycles were verified landing on GitHub.  Lesson for any Store-installed tool a task depends on: never point a scheduled task at `C:\Program Files\WindowsApps\<package>_<version>_...`.

## Notes for whoever picks this up cold

- **Why a separate login instead of sharing `%USERPROFILE%\.claude`?**  The sampler does take the CLI's own refresh lock and re-reads before refreshing, so sharing would mostly work.  But a long-running Claude Code session holds its tokens in memory and refreshes from those, so a rotation by the sampler could still log that session out ([claude-code #24317](https://github.com/anthropics/claude-code/issues/24317) describes the same race between CLI sessions).  A dedicated login removes the race entirely at the cost of one extra `claude login`.  To share the main login anyway, pass `-ConfigDir "$env:USERPROFILE\.claude"` to `install-task.ps1`.
- **Pattern A is still possible** if Anthropic ever stops rotating the token: `collect.py` also accepts `CLAUDE_ACCESS_TOKEN` / `CLAUDE_REFRESH_TOKEN` env vars and writes any rotated pair to `CLAUDE_TOKEN_OUT`.  A workflow would still need a way to persist that file.  Until then, do not create a `sample-claude.yml`.
- **Gaps are expected** while the PC is asleep or Jeff is logged out; the task is Interactive so git can use his stored HTTPS credential.  An always-on host (the NAS) would close those gaps but needs its own `claude login`.
- **Do not hand-edit the sampler clone.**  Uncommitted changes there block the runner's `git pull --rebase` and every push after it fails non-fast-forward until the tree is clean.  Work in a different clone, or commit and push before the next quarter-hour.
- **Site builder mismatch (not this lane's file).**  `site/build.py` treats only `window == "weekly"` as the headline series and otherwise falls back to all rows mixed together, so the Claude line on the chart zigzags between windows.  Suggested one-line fix for the site owner: `weekly = [r for r in rows if r["window"] in ("weekly", "seven_day")] or rows`.  Writing `seven_day` last keeps the card right in the meantime.

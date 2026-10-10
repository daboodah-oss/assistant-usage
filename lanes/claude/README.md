# Claude lane (owner: Fable / Claude), owner-hosted (deployment pattern B)

Samples Jeff's Claude subscription usage every 15 minutes and appends it to `data/claude/usage.csv` per [docs/DATA_CONTRACT.md](../../docs/DATA_CONTRACT.md).  The source is Anthropic's OAuth usage endpoint, the same one Claude Code's `/usage` reads.  It is undocumented, so the parser is defensive.

## Deployment pattern: B, on Jeff's PC

**The Claude Code OAuth refresh token rotates on every use.**  Each refresh returns a new refresh token and invalidates the old one.  Verified against two independent community reports before building: a Stream Deck plugin that refreshed without writing the new token back and logged the CLI out ([stream-deck-ai-limits #12](https://github.com/Sing3Rous/stream-deck-ai-limits/issues/12)), and Clawdmeter's refresh rewrite, which re-reads under the CLI's lock because "a refresh token only works once" ([Clawdmeter #23](https://github.com/weltern/Clawdmeter/pull/23)).

Per [docs/DEPLOYMENT.md](../../docs/DEPLOYMENT.md), a rotating token rules out GitHub Actions: a workflow can read secrets but cannot write the rotated pair back, so the sampler would die at its first refresh (about an hour in).  Two further reasons against pattern A: community reports of Cloudflare answering `403` to token refreshes from datacenter hosts ([claude-code #47754](https://github.com/anthropics/claude-code/issues/47754)), and a write-back workaround would need a second bearer credential (a PAT with secrets write) in the repo.

Fable has no machine of its own that holds a Claude Code login; the login lives on Jeff's PC.  So the sampler runs there as a Windows scheduled task, with its **own** Claude Code login in `%USERPROFILE%\.claude-sampler`, separate from the one Claude Code uses in `%USERPROFILE%\.claude`.  That separation means the sampler and the interactive CLI never rotate each other's tokens.  No GitHub secrets, no lane workflow file, tokens never leave the PC.

## Pieces

| Piece | Path | What |
|-------|------|------|
| Sampler | `lanes/claude/collect.py` | Stdlib Python.  Reads the credentials file, calls the usage endpoint, appends rows.  Refreshes its own token when needed and writes the rotated pair back. |
| Runner | `lanes/claude/run.ps1` | One cycle: `git pull --rebase`, run the sampler, commit `data/claude/usage.csv` if changed, push (rebase and retry on conflict).  Logs to `%LOCALAPPDATA%\assistant-usage\claude-lane.log`. |
| Installer | `lanes/claude/install-task.ps1` | Registers the scheduled task `assistant-usage claude lane` (every 15 min).  `-Uninstall` removes it. |
| Tests | `lanes/claude/test_collect.py` | 29 offline tests with mocked HTTP: `python3 lanes/claude/test_collect.py` |
| Output | `data/claude/usage.csv` | Append-only |
| Handoff | `lanes/claude/PROMPT.md` | The v2 spec |

## How the sampler works

1. Reads `.credentials.json` from `CLAUDE_CONFIG_DIR` (the runner sets this to the sampler's own login dir).  `plan` comes from `claudeAiOauth.subscriptionType` (e.g. `max`), falling back to `rateLimitTier`, then the `CLAUDE_PLAN` env var, then `unknown`.
2. If the access token expires within 2 minutes, refreshes first.  Otherwise calls `GET https://api.anthropic.com/api/oauth/usage` with `Authorization: Bearer`, `anthropic-beta: oauth-2025-04-20`, `User-Agent: claude-code/2.0.0`.
3. On `401`, refreshes once: `POST https://platform.claude.com/v1/oauth/token`, form-encoded, `grant_type=refresh_token`, Claude Code's public client id (`console.anthropic.com` only if the first host answers 404/405/redirect/network error).  Done under the same `mkdir`-style lock Claude Code uses (`<config dir>/.oauth_refresh.lock`, stale after 60 s).  After taking the lock it re-reads the file; if something else already rotated the token, it uses that one instead of refreshing.  The rotated pair is written back atomically, preserving every other field.  Then it retries the usage call once.  Never loops.
4. Writes one row per window.  Unrecognized shape or any failure: writes **nothing** and exits 0.  A missing row is honest; a zero is a lie.  A genuine 0% is written as 0.
5. Skips if the last sample is under 2 minutes old (contract rule 6).  A lockfile in the temp dir stops overlapping runs on the same machine.

Every run prints one status line (`claude-collector: status=ok rows=3 windows=... plan=max creds=file refreshed=false`, or `status=nothing_written reason=...`), and the runner copies it to the log.  The process exit code is always 0; the log is the signal.

### Windows (CSV `window` column)

| `window` | Meaning |
|----------|---------|
| `five_hour` | Rolling 5-hour session limit.  `reset_iso` is when the current window ends. |
| `seven_day` | Weekly limit across all models. |
| `weekly_<model>` | A separate weekly cap on one model, e.g. `weekly_fable_5`.  Anthropic rotates which model has one, so the label comes from the API's `limits[]` entries. |

`usage_pct` is percent **used** (0 to 100).  `raw` holds only whitelisted fields (`kind`, `utilization` or `percent`, `resets_at`, model name), so nothing sensitive can reach `data/`.  Each run writes `seven_day` last, so the shared page's Claude card shows the weekly figure (see the site note below).

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

## Re-provisioning (when the login dies)

Symptoms: the Claude card on the page goes stale, and the log shows `refresh_failed_relogin_needed`, `401_after_refresh`, or `no_credentials`.  Causes are a revoked session, a password change, or the sampler not having run for long enough that the refresh token itself expired.

Fix: repeat step 2 above (the same `claude login` with the sampler config dir).  The task picks the new login up on its next run; nothing else changes.  The sampler never retries in a loop, so a dead login costs one failed refresh per 15 minutes and nothing more.

Other log lines and what they mean:

| Log says | Meaning |
|----------|---------|
| `no change` | Sampler wrote nothing this cycle (see the `collect:` line before it for why). |
| `WARN pull failed` | Local clone diverged; the runner aborted the rebase and tried anyway.  If it persists, re-clone. |
| `ERROR push failed after 3 attempts` | Network or auth.  The commit is kept locally and the next run retries. |
| `refresh_lock_busy` | Another process held the refresh lock for 15 s.  Harmless once; recurring means a stuck process. |
| `unrecognized_shape` | The endpoint changed.  The log lists the top-level keys it saw.  Update `parse_usage()` in `collect.py`. |

## Notes for whoever picks this up cold

- **Why a separate login instead of sharing `%USERPROFILE%\.claude`?**  The sampler does take the CLI's own refresh lock and re-reads before refreshing, so sharing would mostly work.  But a long-running Claude Code session holds its tokens in memory and refreshes from those, so a rotation by the sampler could still log that session out ([claude-code #24317](https://github.com/anthropics/claude-code/issues/24317) describes the same race between CLI sessions).  A dedicated login removes the race entirely at the cost of one extra `claude login`.  To share the main login anyway, pass `-ConfigDir "$env:USERPROFILE\.claude"` to `install-task.ps1`.
- **Pattern A is still possible** if Anthropic ever stops rotating the token: `collect.py` also accepts `CLAUDE_ACCESS_TOKEN` / `CLAUDE_REFRESH_TOKEN` env vars and writes any rotated pair to `CLAUDE_TOKEN_OUT`.  A workflow would still need a way to persist that file.
- **Gaps are expected** while the PC is asleep or Jeff is logged out; the task is Interactive so git can use his stored HTTPS credential.  An always-on host (the NAS) would close those gaps but needs its own `claude login`.
- **Site builder mismatch (not this lane's file).**  `site/build.py` treats only `window == "weekly"` as the headline series and otherwise falls back to all rows mixed together, so the Claude line on the chart zigzags between windows.  Suggested one-line fix for the site owner: `weekly = [r for r in rows if r["window"] in ("weekly", "seven_day")] or rows`.  Writing `seven_day` last keeps the card right in the meantime.
- **Not yet verified live.**  Parser and refresh flow were tested offline against mocked responses and the community-documented shapes.  Acceptance (three consecutive cycles with every window) is confirmed after Jeff's step 3.

# Claude lane (owner: Fable / Claude)

Samples Jeff's Claude subscription usage every 15 minutes and appends it to `data/claude/usage.csv` per [docs/DATA_CONTRACT.md](../../docs/DATA_CONTRACT.md).  The source is Anthropic's OAuth usage endpoint, the same one Claude Code's `/usage` reads.  It is undocumented, so the parser is defensive.

| Piece | Path |
|-------|------|
| Sampler | `lanes/claude/collect.py` (stdlib only) |
| Offline tests | `lanes/claude/test_collect.py` (`python3 lanes/claude/test_collect.py`) |
| Schedule | `.github/workflows/sample-claude.yml` |
| Output | `data/claude/usage.csv` |
| Original handoff | `lanes/claude/PROMPT.md` |

## How it works

1. `GET https://api.anthropic.com/api/oauth/usage` with the access token, `anthropic-beta: oauth-2025-04-20`, and `User-Agent: claude-code/2.0.0`.
2. On `401`, refresh once (`POST https://platform.claude.com/v1/oauth/token`, form-encoded, `grant_type=refresh_token`, Claude Code's public client id; `console.anthropic.com` is tried only if the first host answers 404/405/redirect/network error).  Retry the usage call once.  Never loop.
3. Write one row per window.  If the response shape is not recognized, or anything fails, write **nothing** and exit 0.  A missing row is honest; a zero is a lie.  A genuine 0% is written as 0.
4. Skip if the last sample is under 2 minutes old (contract rule 6).  A lockfile stops overlapping local runs, and the workflow's `concurrency` group does the same across runs.
5. The workflow commits the CSV (rebase and retry on conflict), then dispatches `build-site` so the page updates.  Pushes made with `GITHUB_TOKEN` do not trigger other workflows on their own, hence the explicit dispatch.

The job summary of every run shows one status line (`status=ok rows=3 ...` or `status=nothing_written reason=...`), because the job stays green even when nothing was recorded.

### Windows (columns in the CSV)

| `window` | Meaning |
|----------|---------|
| `five_hour` | Rolling 5-hour session limit.  `reset_iso` is when the current window ends. |
| `seven_day` | Weekly limit across all models. |
| `weekly_<model>` | A separate weekly cap on one model, e.g. `weekly_fable_5`.  Anthropic rotates which model has one, so the label comes from the API. |

`usage_pct` is percent **used** (0 to 100), not remaining.  `raw` holds only whitelisted fields (`kind`, `utilization`/`percent`, `resets_at`, model name), so secrets cannot leak into `data/`.  `plan` comes from the optional `CLAUDE_PLAN` repo variable (default `unknown`), because the plan label lives in Claude Code's credentials file and is not available from the two token secrets.

## Why tokens need extra care

Claude Code's refresh token **rotates**: each refresh returns a new one and kills the old one.  A GitHub secret cannot update itself, so the workflow writes rotated tokens back to the repo secrets using one extra fine-grained token (`CLAUDE_SECRETS_PAT`).  Without it the sampler refuses to refresh at all (`CLAUDE_NO_REFRESH=1`), which is non-destructive but means data stops when the access token expires, roughly an hour after provisioning.

Also, if the sampler shares the login Claude Code uses on Jeff's PC, the first rotation breaks the PC's login.  So the sampler gets its **own** login (step 1 below).

## Provisioning (Jeff does this)

These are bearer tokens to your paid Claude account.  Treat them like passwords: only paste them into GitHub's secret form, never into chat, never into a file in the repo.

**1. Give the sampler its own Claude Code login (PowerShell on your PC)**

```powershell
$env:CLAUDE_CONFIG_DIR = "$env:USERPROFILE\.claude-sampler"
claude login
notepad "$env:USERPROFILE\.claude-sampler\.credentials.json"
```

Use this window only for the login.  Never run Claude Code with that config dir again, or you will rotate the tokens out from under the workflow.

**2. Create the two secrets**

GitHub repo, Settings, Secrets and variables, Actions, New repository secret:

| Secret name | Value from `.credentials.json` |
|-------------|--------------------------------|
| `CLAUDE_ACCESS_TOKEN` | `claudeAiOauth.accessToken` |
| `CLAUDE_REFRESH_TOKEN` | `claudeAiOauth.refreshToken` |

Close Notepad without saving, then delete `%USERPROFILE%\.claude-sampler\.credentials.json`.  The copies in GitHub are the live ones from now on.

**3. Create the write-back token**

GitHub, Settings, Developer settings, Fine-grained personal access tokens, Generate new token.  Resource owner `daboodah-oss`, repository access **only** `assistant-usage`, repository permission **Secrets: Read and write**, nothing else.  Pick an expiry you will remember.  Save it as repo secret `CLAUDE_SECRETS_PAT`.

**4. (Optional) Set the plan label**

Same page, Variables tab, New repository variable `CLAUDE_PLAN` with your subscription type, e.g. `max`.

**5. Run it once by hand**

Actions tab, `sample-claude`, Run workflow.  Open the run and read the job summary.  Expect `status=ok` with `five_hour`, `seven_day` and any `weekly_<model>` windows.

## When the login dies (re-provisioning)

Symptoms: no new rows, and the job summary says `refresh_failed_relogin_needed`, `401_after_refresh`, or `401_and_refresh_disabled`.  Repeat steps 1 and 2 (a fresh separate login, overwrite the two secrets).  The PAT and variable stay as they are.  Do not retry in a loop: the sampler already attempts at most one refresh per run.

## Known risks and handoff notes

- **Datacenter blocking (untested).**  Community reports say Cloudflare sometimes answers `403` to token refreshes from headless Linux hosts.  If the first rotation logs `refresh: platform.claude.com returned status 403`, the lane cannot self-sustain from GitHub runners.  The same `collect.py` runs anywhere with the same env vars, for example Task Scheduler on the PC, as a fallback.
- **Undocumented endpoint.**  If its shape changes, rows stop (honestly) and the log lists the top-level keys it saw.
- **Site builder mismatch (not this lane's file).**  `site/build.py` treats only `window == "weekly"` as the headline series and otherwise falls back to all rows mixed together.  This lane follows the spec's window names, so the Claude line would zigzag between windows.  Suggested one-line fix for the site owner: `weekly = [r for r in rows if r["window"] in ("weekly", "seven_day")] or rows`.  Until then, each run writes `seven_day` as its last row so the Claude card shows the weekly figure.
- **Not yet verified live.**  The parser and refresh flow were tested offline against mocked responses and the community-documented shapes.  Acceptance (three consecutive runs with every window) can only be confirmed after step 5.

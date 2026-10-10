# Lane handoff: Claude usage sampler (v2 — deployment is your choice)

> Jeff: paste everything below this line to Claude (Fable).

---

You own the `claude` lane of the repo `daboodah-oss/assistant-usage` — a
unified usage dashboard for Jeff's three AI assistants (Muse, Claude, Grok).
Your job: feed his Claude subscription usage into the shared page.

## Read first (in the repo)

1. `README.md` — project overview and the lane rule
2. `docs/DATA_CONTRACT.md` — the exact CSV schema you must write
3. `docs/DEPLOYMENT.md` — deployment patterns (read this before choosing)
4. `docs/SECRETS.md` — credential rules

## Step 0: determine your deployment pattern

The Grok lane discovered that rotating refresh tokens break GitHub Actions
(a workflow can read repo secrets but cannot write a rotated token back, so
the sampler dies at the first refresh). Before building, determine whether
your Claude Code OAuth refresh token **rotates on use**:

- **It does NOT rotate** (or your tooling persists the rotated pair
  somewhere the sampler can read): use **pattern A — GitHub Actions**.
  Build `.github/workflows/sample-claude.yml` (cron every 15 min) with
  `CLAUDE_ACCESS_TOKEN` / `CLAUDE_REFRESH_TOKEN` as secrets (Jeff provisions
  them: `claude login` on his PC, copy from
  `%USERPROFILE%\.claude\.credentials.json`). NOTE: pushing workflow files
  via the GitHub API needs the `workflow` scope — if rejected with 404, add
  the file through the GitHub web UI and tell Jeff.
- **It rotates** (or you can't verify): use **pattern B — owner-hosted**,
  like the grok and muse lanes. Run the sampler where your Claude Code login
  lives, on a 15-minute routine that commits `data/claude/usage.csv`. No
  GitHub secrets, no workflow file, tokens never leave your machine.

State your choice and why in `lanes/claude/README.md`.

## Lane discipline

- Work ONLY in `lanes/claude/` and `data/claude/`. Never touch other lanes,
  `site/`, or anyone else's workflow.
- Branch protection is Tier 2: commit straight to `main`, never force-push.

## What to build

**`lanes/claude/collect.py`** (Python 3, stdlib + `requests` if available):
- `GET https://api.anthropic.com/api/oauth/usage` with headers
  `Authorization: Bearer <token>`, `anthropic-beta: oauth-2025-04-20`,
  `User-Agent: claude-code/2.0.0`
  (the same endpoint Claude Code's `/usage` reads; undocumented — parse
  defensively)
- Write **one row per window per run** to `data/claude/usage.csv`:
  `five_hour` and `seven_day` windows (utilization %, `resets_at`), plus one
  row per per-model weekly bucket in `limits[]` (`window` = `weekly_<model>`).
  `plan` comes from the token's subscription/rate-limit tier.
- The token is a Claude Code OAuth token, NOT an Anthropic API key
  (an API key returns `Invalid bearer token` here).
- On 401: refresh with the refresh token using the standard Claude Code
  OAuth refresh flow — verify the endpoint against a working community
  implementation, do not invent one — retry once, then write nothing and
  exit 0. On any unrecognized response shape: write nothing, exit 0.
  A missing row is honest; a zero or a guess is a lie.
- If pattern A: read tokens from env vars; use a lockfile so concurrent runs
  can't double-rotate the refresh token.

Plus **`lanes/claude/README.md`**: your pattern choice and why, how it
works, what each window means, how the login gets re-provisioned.

## What Jeff must do

- Pattern A: `claude login` on his PC, then the two tokens into repo secrets
  (spell the exact steps out for him — they're bearer tokens to his paid
  account).
- Pattern B: nothing, unless the login lives somewhere he must set up.

## Acceptance

- Three consecutive runs/routine cycles append rows for every window.
- The unified page shows a Claude panel with current % and reset countdown.
- `git log -p -- lanes/claude data/claude | grep -iE 'token|bearer'` shows
  nothing sensitive.

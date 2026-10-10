# Lane handoff: Claude usage sampler

> Jeff: paste everything below this line to Claude (Fable).

---

You own the `claude` lane of the repo `daboodah-oss/assistant-usage` — a
unified usage dashboard for Jeff's three AI assistants (Muse, Claude, Grok).
Your job: build a sampler that records his Claude subscription usage every
15 minutes so it appears on the shared page.

## Read first (in the repo)

1. `README.md` — project overview and the lane rule
2. `docs/DATA_CONTRACT.md` — the exact CSV schema your sampler must write
3. `docs/SECRETS.md` — how credentials are stored (never committed, never logged)

## Lane discipline

- Work ONLY in `lanes/claude/` and `data/claude/`. Never touch other lanes,
  `site/`, or anyone else's workflow.
- Branch protection is Tier 2: commit straight to `main`, never force-push.

## What to build

1. **`lanes/claude/collect.py`** (Python 3, stdlib + `requests` if available):
   - `GET https://api.anthropic.com/api/oauth/usage` with headers
     `Authorization: Bearer $CLAUDE_ACCESS_TOKEN`,
     `anthropic-beta: oauth-2025-04-20`,
     `User-Agent: claude-code/2.0.0`
     (this is the same endpoint Claude Code's `/usage` reads; it is
     undocumented, so parse defensively)
   - Write **one row per window per run** to `data/claude/usage.csv`:
     `five_hour` and `seven_day` windows (utilization %, `resets_at`), plus one
     row per per-model weekly bucket in `limits[]` (`window` = `weekly_<model>`).
     `plan` comes from the token's subscription/rate-limit tier.
   - Auth: the token is a Claude Code OAuth token, NOT an Anthropic API key
     (an API key returns `Invalid bearer token` here). On 401, refresh with
     `CLAUDE_REFRESH_TOKEN` using the standard Claude Code OAuth refresh flow
     — verify the endpoint against a working community implementation, do not
     invent one — retry once, then write nothing and exit 0.
   - On any unrecognized response shape: write nothing, exit 0. A missing row
     is honest; a zero or a guess is a lie.
   - Use a lockfile so concurrent runs can't double-rotate the refresh token.
2. **`.github/workflows/sample-claude.yml`**: cron every 15 min — run
   `collect.py` with the two secrets as env vars, commit
   `data/claude/usage.csv` if it changed, push.
3. **`lanes/claude/README.md`**: how it works, what each window means, and how
   Jeff re-provisions the login when the refresh token dies.

## What Jeff must do (he does this, not you — spell it out for him)

1. On his PC, make sure Claude Code is logged in (`claude login` if needed).
2. Open `%USERPROFILE%\.claude\.credentials.json`, copy
   `claudeAiOauth.accessToken` → repo secret `CLAUDE_ACCESS_TOKEN` and
   `claudeAiOauth.refreshToken` → repo secret `CLAUDE_REFRESH_TOKEN`
   (GitHub repo Settings → Secrets and variables → Actions → New repository
   secret). Warn him these are bearer tokens to his paid account.

## Acceptance

- Three consecutive workflow runs append rows for every window.
- The unified page shows a Claude panel with current % and reset countdown.
- `git log -p -- lanes/claude data/claude | grep -iE 'token|bearer'` shows
  nothing sensitive.

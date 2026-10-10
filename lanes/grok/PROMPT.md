# Lane handoff: Grok usage sampler

> Jeff: paste everything below this line to Grok (Ara).

---

You own the `grok` lane of the repo `daboodah-oss/assistant-usage` — a unified
usage dashboard for Jeff's three AI assistants (Muse, Claude, Grok). Your job:
build a sampler that records his Grok (SuperGrok) subscription usage every
15 minutes so it appears on the shared page.

## Read first (in the repo)

1. `README.md` — project overview and the lane rule
2. `docs/DATA_CONTRACT.md` — the exact CSV schema your sampler must write
3. `docs/SECRETS.md` — how credentials are stored (never committed, never logged)

## Lane discipline

- Work ONLY in `lanes/grok/` and `data/grok/`. Never touch other lanes,
  `site/`, or anyone else's workflow.
- Branch protection is Tier 2: commit straight to `main`, never force-push.

## What to build

1. **`lanes/grok/collect.py`** (Python 3, stdlib + `requests` if available):
   - `GET https://cli-chat-proxy.grok.com/v1/user?include=subscription` →
     `userId` and plan tier. Headers on every call:
     `Authorization: Bearer $GROK_ACCESS_TOKEN`,
     `X-XAI-Token-Auth: xai-grok-cli`, plus a client identifier/version.
     (These are the same first-party endpoints the official Grok CLI uses;
     they are undocumented, so parse defensively. A plain xAI API key does
     NOT work here.)
   - `GET https://cli-chat-proxy.grok.com/v1/billing?format=credits` with the
     `userId` in an `x-userid` header → `config.creditUsagePercent` (the
     headline weekly-pool % — this is your `usage_pct`), `billingPeriodEnd`
     (your `reset_iso`), plan tier (your `plan`), `window` = `weekly`.
     Optionally also write one row per entry of `config.productUsage[]`
     (`window` = `weekly_<product>`, `usage_pct` = its `usagePercent`).
   - Fields vary by account/rollout: if `creditUsagePercent` is absent, write
     nothing (empty `usage_pct`), exit 0. Never treat missing as zero.
   - Access tokens last ~6h: refresh via `auth.x.ai` with
     `GROK_REFRESH_TOKEN` (rotating — verify the flow against a working
     community implementation, do not invent it). On 401, refresh, retry
     once; on second 401 write nothing and exit 0.
   - Use a lockfile so concurrent runs can't double-rotate the refresh token.
2. **`.github/workflows/sample-grok.yml`**: cron every 15 min — run
   `collect.py` with the two secrets as env vars, commit
   `data/grok/usage.csv` if it changed, push.
3. **`lanes/grok/README.md`**: how it works and how Jeff re-provisions the
   login when the refresh token dies.

## What Jeff must do (he does this, not you — spell it out for him)

1. Install the official Grok CLI and run `grok login` (browser OAuth).
2. Open `~/.grok/auth.json`, copy the access token → repo secret
   `GROK_ACCESS_TOKEN` and the refresh token → `GROK_REFRESH_TOKEN`
   (GitHub repo Settings → Secrets and variables → Actions → New repository
   secret). Warn him these are bearer tokens to his account.

## Acceptance

- Three consecutive workflow runs append rows.
- The unified page shows a Grok panel with current % and reset countdown.
- `git log -p -- lanes/grok data/grok | grep -iE 'token|bearer'` shows
  nothing sensitive.

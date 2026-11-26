# Lane handoff: Grok usage sampler (v2 — owner-hosted)

> Jeff: paste everything below this line to Grok (Keela).

---

You own the `grok` lane of the repo `daboodah-oss/assistant-usage` — a unified
usage dashboard for Jeff's three AI assistants (Muse, Claude, Grok). Your job:
feed your Grok (SuperGrok) subscription usage into the shared page.

## Current push and heartbeat (2026-11-26)

Pushes are HTTPS-only to `https://github.com/daboodah-oss/assistant-usage.git`
`HEAD:main` via `GROK_FEED_GH_TOKEN` (box environment, `GIT_CONFIG_*` credential
helper, value never printed). The SSH fallback was retired on 2026-11-26:
Pingora blocks SSH CONNECT to ssh.github.com:443. If the token is absent,
`lanes/grok/push_feed.py` fails with `PUSH fail reason=GROK_FEED_GH_TOKEN_unset`.

Healthchecks: use `GROK_FEED_HC_URL` when it is set. When it is unset or empty,
`lanes/grok/feed-run.sh` reads `/workspace/grok-feed/state/.hc_ping_url`
(mode 0600, box-owned, trailing whitespace stripped). The URL is never printed
or logged. Details: `lanes/grok/README.md` and `docs/SECRETS.md`.

## Read first (in the repo)

1. `README.md` — project overview and the lane rule
2. `docs/DATA_CONTRACT.md` — the exact CSV schema you must write
3. `docs/DEPLOYMENT.md` — deployment patterns (you are pattern B: owner-hosted)
4. `docs/SECRETS.md` — you need **no GitHub secrets** under this pattern

## Decision (already made)

You flagged that the Grok refresh token rotates on every use and GitHub
Actions cannot write rotated tokens back into repo secrets — so the Actions
pattern is out. You run **owner-hosted**: your box, your existing tracker,
your login. No tokens ever leave your computer, no lane workflow file.

## Lane discipline

- Work ONLY in `lanes/grok/` and `data/grok/`. Never touch other lanes,
  `site/`, or anyone else's workflow.
- Branch protection is Tier 2: commit straight to `main`, never force-push.

## What to build

1. **`lanes/grok/collect.py`**: reads the latest reading from your existing
   usage tracker (the one sampling the billing endpoint every 5 minutes) and
   writes **one row** to `data/grok/usage.csv` per the data contract:
   `usage_pct` = `creditUsagePercent`, `reset_iso` = `billingPeriodEnd`,
   `plan` = subscription tier, `window` = `weekly`. Optionally one extra row
   per `config.productUsage[]` entry (`window` = `weekly_<product>`).
   If the tracker has no fresh reading (or the field is absent), write
   nothing — never treat missing as zero.
2. **A 15-minute routine on your box**: run `collect.py`, commit
   `data/grok/usage.csv` if it changed, push to `main`. Every push to
   `data/**` triggers the repo's `build-site` workflow, so your panel appears
   automatically.
3. **`lanes/grok/README.md`**: update it to describe owner-hosted operation —
   where the tracker lives, how the login survives rebuilds, how Jeff (or a
   future you) re-provisions it.

## What Jeff must do

The lane runs on the box, so there is still no GitHub Actions secret for it.
Jeff provisions `GROK_FEED_GH_TOKEN` in the box environment (HTTPS push) and,
if he wants the off-box feed check, either `GROK_FEED_HC_URL` or the box file
`/workspace/grok-feed/state/.hc_ping_url` (mode 0600). See `docs/SECRETS.md`.

## Acceptance

- Three consecutive routine runs commit fresh rows.
- The unified page shows a Grok panel with current % and reset countdown.
- No token material anywhere in the repo history.

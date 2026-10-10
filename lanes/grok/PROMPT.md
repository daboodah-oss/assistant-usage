# Lane handoff: Grok usage sampler (v2 — owner-hosted)

> Jeff: paste everything below this line to Grok (Ara).

---

You own the `grok` lane of the repo `daboodah-oss/assistant-usage` — a unified
usage dashboard for Jeff's three AI assistants (Muse, Claude, Grok). Your job:
feed your Grok (SuperGrok) subscription usage into the shared page.

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

Nothing on this lane. No login, no secrets.

## Acceptance

- Three consecutive routine runs commit fresh rows.
- The unified page shows a Grok panel with current % and reset countdown.
- No token material anywhere in the repo history.

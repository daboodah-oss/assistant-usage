# Muse lane (owner: Budzilla)

Samples Jeff's Muse subscription via the `subscription-status` CLI, which only
exists on Budzilla's VM — so this lane runs there, not in GitHub Actions.

- `collect.py` appends one row per run to `data/muse/usage.csv`
  (see `docs/DATA_CONTRACT.md`). `window` is always `weekly`;
  `plan` is the tier (`free`, `power`, …).
- Cron `assistant-usage-muse-sampler` (every 15 min) runs `collect.py`, then
  uploads the CSV via `gh.py push-file` (only this VM writes that file, so a
  full-file upload is safe).
- The collector auto-detects plan changes (free → power on 2026-10-10).

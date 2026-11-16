# Muse lane (owner: Budzilla)

Samples Jeff's Muse subscription via the `subscription-status` CLI, which only
exists on Budzilla's VM — so this lane runs there, not in GitHub Actions.

- `collect.py` appends one row per run to `data/muse/usage.csv`
  (see `docs/DATA_CONTRACT.md`). `window` is always `weekly`;
  `plan` is the tier (`free`, `power`, …).
- Cron `assistant-usage-muse-sampler` (every 15 min) runs `collect.py`, then
  `push_git.py`: it re-syncs the transport clone at
  `~/workspace/assistant-usage-clone`, copies the CSV in, commits if changed,
  and pushes via real git (delta transport). This replaced `gh.py push-file`
  on 2026-11-15 — the Contents API re-uploads the whole file every run and
  caps files at 1 MB, which the growing CSV was about to hit.
- Push auth: repo-scoped deploy key `~/.ssh/assistant_usage_deploy` (write,
  this repo only; repo Settings -> Deploy keys, "Budzilla VM muse lane
  pusher"), reaching ssh.github.com:443 through the VM egress proxy's HTTP
  CONNECT tunnel (`ssh_proxy.py`); the clone's `core.sshCommand` wires both.
  If pushes fail with auth errors, check that deploy key still exists.
- `watch_grok.py` runs at the end of the same cron: an off-box freshness
  watch for the grok lane (Jeff approved 2026-11-15). If the newest
  `window=weekly` row in `data/grok/usage.csv` on main is over 2 hours
  old, it prints one alert line for Jeff; a state file next to the muse
  CSV keeps it to one alert per outage. It exists because a Grok-side
  outage (pool exhausted, box hibernated) silences every on-box alarm.
- The collector auto-detects plan changes (free → power on 2026-10-10).

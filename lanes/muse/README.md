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
- The collector auto-detects plan changes (free → power on 2026-10-10).

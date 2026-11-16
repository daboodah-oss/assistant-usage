# Secrets

Bearer tokens are passwords. Least privilege, never committed, never logged,
never pasted into chat.

Lanes that run **owner-hosted** (see `docs/DEPLOYMENT.md` pattern B) need **no
GitHub secrets at all** — tokens stay on the owner's machine. Only lanes
running in GitHub Actions (pattern A) use the secrets below, stored in repo
Settings → Secrets and variables → Actions and consumed only by that lane's
sampler workflow.

| Secret(s) | Lane | What it is | Provisioned by |
|-----------|------|-----------|----------------|
| Deploy keys (SSH; private halves on Budzilla's VM only) | `muse` | Repo-scoped GitHub deploy keys with write access, one per repo: assistant-usage ("Budzilla VM muse lane pusher", private half `~/.ssh/assistant_usage_deploy`) and muse-usage-tracker ("Budzilla VM muse tracker pusher", private half `~/.ssh/muse_tracker_deploy`). Both reach ssh.github.com:443 through the VM egress proxy's HTTP CONNECT tunnel. Revoke per repo under Settings -> Deploy keys. The lane also uses the local `subscription-status` CLI session. | Budzilla (pairs generated on the VM; only the public halves left it) |
| Deploy key (SSH; private half on Keela's box only) | `grok` | Repo-scoped GitHub deploy key with write access to assistant-usage only, titled "keela-box grok lane". Private half `~/.ssh/grok_feed_deploy` on Keela's box (mode 600, outside any repo); used only by `lanes/grok/feed-run.sh` via the transport clone's `core.sshCommand`, reaching ssh.github.com:443 through the box egress proxy's HTTP CONNECT tunnel (`lanes/grok/ssh_proxy.py`). Revoke under Settings -> Deploy keys; then the feed fails closed (rows stay local). The box also holds its own Grok CLI login (`~/.grok/auth.json`, rotating; never leaves the box). Optional box secret `GROK_FEED_HC_URL` (healthchecks.io ping URL for the feed check) if Jeff creates one. | Keela (pair generated on the box; only the public half left it); Jeff adds the public half |
| `CLAUDE_ACCESS_TOKEN`, `CLAUDE_REFRESH_TOKEN` | `claude` | Claude Code OAuth token pair — **only if** the lane runs in GitHub Actions (pattern A); not needed for owner-hosted | Jeff: `claude login` on his PC, copy from Claude Code's credentials file |

## Rules

- Samplers read secrets from environment variables only.
- If a sampler gets 2 consecutive 401s after attempting a refresh, it writes
  **nothing** and exits 0. The lane owner tells Jeff the login needs redoing.
  Never retry in a tight loop.
- Token refresh happens inside the sampler (both platforms issue rotating
  refresh tokens). Use a lockfile so concurrent runs can't double-rotate.
- Spot-check before handing off: `git log -p -- lanes/<name> data/<name> |
  grep -iE 'token|secret|bearer'` must show nothing sensitive.

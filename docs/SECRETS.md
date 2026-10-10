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
| — | `muse` | none — owner-hosted; uses the local `subscription-status` CLI session on Budzilla's VM | — |
| — | `grok` | none — owner-hosted; Ara's box holds its own Grok CLI login | — |
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

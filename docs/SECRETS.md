# Secrets

Bearer tokens are passwords. Least privilege, never committed, never logged,
never pasted into chat. All lane secrets live in GitHub Actions secrets
(repo Settings → Secrets and variables → Actions), consumed only by that
lane's sampler workflow.

| Secret(s) | Lane | What it is | Provisioned by |
|-----------|------|-----------|----------------|
| — | `muse` | none — runs on Budzilla's VM, uses the local `subscription-status` CLI session | — |
| `CLAUDE_ACCESS_TOKEN`, `CLAUDE_REFRESH_TOKEN` | `claude` | Claude Code OAuth token pair | Jeff: `claude login` on his PC, copy from Claude Code's credentials file |
| `GROK_ACCESS_TOKEN`, `GROK_REFRESH_TOKEN` | `grok` | Grok CLI OAuth token pair | Jeff: `grok login`, copy from `~/.grok/auth.json` |

## Rules

- Samplers read secrets from environment variables only.
- If a sampler gets 2 consecutive 401s after attempting a refresh, it writes
  **nothing** and exits 0. The lane owner tells Jeff the login needs redoing.
  Never retry in a tight loop.
- Token refresh happens inside the sampler (both platforms issue rotating
  refresh tokens). Use a lockfile so concurrent runs can't double-rotate.
- Spot-check before handing off: `git log -p -- lanes/<name> data/<name> |
  grep -iE 'token|secret|bearer'` must show nothing sensitive.

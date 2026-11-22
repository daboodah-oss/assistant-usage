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
| `GROK_FEED_GH_TOKEN` (box env; HTTPS push, primary) | `grok` | GitHub fine-grained personal access token, created by Jeff Sat Nov 21, 2026 (approved 7:00 PM ET). Resource owner `daboodah-oss`; repository access **only** `daboodah-oss/assistant-usage`; permission **Contents: read and write**, nothing else. Expires Fri Feb 19, 2027, 8:44 PM ET (2027-02-20 01:44 UTC, per GitHub's token-expiration header; 90 days); the date (never the token) is recorded as `GROK_FEED_TOKEN_EXPIRES_UTC` in `lanes/grok/feed.conf`. Lives only in the box environment of Keela's box: never in a file, URL, remote, `.git/config`, argv, log, chat or commit. Used only by `lanes/grok/push_feed.py`. **Push order (Option 3, Variant A; Jeff approved Sun Nov 22, 2026 ~3:26 PM ET, after xAI ticket T-K97957 said SSH from the box is unsupported):** with the token set, every push goes to `https://github.com/daboodah-oss/assistant-usage.git` `HEAD:main` **first** (never forced) via a credential helper passed in `GIT_CONFIG_*` env vars, and only if HTTPS fails is the same commit pushed over SSH with the deploy key above; output is scrubbed and the PUSH line says `via=https` (primary) or `via=ssh_fallback https_err=...`. `--dry-run --probe-push` probes HTTPS. If the token is unset, the feed is SSH-only exactly as before PR #12. **Alerts:** an HTTPS failure that looks like token auth (401/403, `Authentication failed`, `Invalid username or password`, `Permission to ... denied`) adds `https_auth_fail=1` to the PUSH line; `feed-run.sh` records `last_push_auth_fail` / `push_auth_state` in `status.json` and prints `ALERT grok-feed push token auth failed ...` once per incident and `ALERT grok-feed push token auth recovered ...` when HTTPS works again; the 30-minute feed wake relays ALERT lines to Jeff. `feed-run.sh` also prints one `ALERT grok-feed GROK_FEED_GH_TOKEN expires ...` when `GROK_FEED_TOKEN_EXPIRES_UTC` is 14 days away. **Renewal reminder:** Grok Bot routine "Grok feed token renewal reminder" (id `grok-feed-token-renewal-reminder`) messages Jeff Fri Feb 5 and Mon Feb 15, 2027 at 9:00 AM ET. **Revoke:** GitHub (Jeff's account) -> Settings -> Developer settings -> Personal access tokens -> Fine-grained tokens -> this token -> Revoke; then remove the variable from the box env (the feed drops to SSH-only). **Before Feb 19, 2027:** Jeff regenerates or replaces it with the same scope (repo only, Contents read/write), Keela updates the box env and `GROK_FEED_TOKEN_EXPIRES_UTC` via a keela/ PR; otherwise HTTPS pushes fail on auth (ALERT) and the feed relies on the SSH fallback. | Jeff (created on GitHub); Keela consumes it on the box |
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

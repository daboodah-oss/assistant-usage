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
| Deploy key (SSH; retired 2026-11-26; private half on Keela's box only) | `grok` | Repo-scoped GitHub deploy key with write access to assistant-usage only, titled "keela-box grok lane". Private half `~/.ssh/grok_feed_deploy` on Keela's box (mode 600, outside any repo). **Retired 2026-11-26 (R8, Budzilla and Jeff):** the Grok lane no longer pushes over SSH and no longer runs an SSH drill. Pingora, the box egress proxy, rejects SSH CONNECT to ssh.github.com:443 with HTTP 400. `lanes/grok/feed-run.sh` does not set `core.sshCommand` or `remote.origin.pushurl`, and `lanes/grok/ssh_proxy.py` is a retired stub that does not open a tunnel (kept only so a feed-run.sh from before this change can still load that path from origin/main once). The key is unused by the lane; Jeff may revoke it under Settings -> Deploy keys. The box still holds its own Grok CLI login (`~/.grok/auth.json`, rotating; never leaves the box). Healthchecks: optional box env `GROK_FEED_HC_URL`. If that variable is unset or empty, `feed-run.sh` reads `/workspace/grok-feed/state/.hc_ping_url` (mode 0600, box-owned; trailing whitespace stripped). The env var wins when it is set. The URL is never printed or logged. | Keela (pair generated on the box; only the public half left it); Jeff may revoke the unused public half |
| `GROK_FEED_GH_TOKEN` (box env; HTTPS push, only path) | `grok` | GitHub fine-grained personal access token, created by Jeff Sat Nov 21, 2026 (approved 7:00 PM ET). Resource owner `daboodah-oss`; repository access **only** `daboodah-oss/assistant-usage`; permission **Contents: read and write**, nothing else. Expires Fri Feb 19, 2027, 8:44 PM ET (2027-02-20 01:44 UTC, per GitHub's token-expiration header; 90 days); the date (never the token) is recorded as `GROK_FEED_TOKEN_EXPIRES_UTC` in `lanes/grok/feed.conf`. Lives only in the box environment of Keela's box: never in a file, URL, remote, `.git/config`, argv, log, chat or commit. Used only by `lanes/grok/push_feed.py`. **Push (HTTPS only; R8, Budzilla and Jeff, 2026-11-26):** every push goes to `https://github.com/daboodah-oss/assistant-usage.git` `HEAD:main` (never forced) via a credential helper passed in `GIT_CONFIG_*` env vars. Output is scrubbed and a successful PUSH line says `via=https`. There is no SSH fallback and no monthly SSH drill (Pingora rejects SSH CONNECT to ssh.github.com:443 with HTTP 400). This replaces Option 3 Variant A (HTTPS first, SSH fallback; Jeff, Sun Nov 22, 2026). If `GROK_FEED_GH_TOKEN` is unset or empty, `push_feed.py` prints `PUSH fail reason=GROK_FEED_GH_TOKEN_unset` and exits 1 without pushing; rows stay in the local CSV. `--dry-run --probe-push` probes HTTPS when the token is set, and reports `probe_push=fail(GROK_FEED_GH_TOKEN_unset)` when it is not. **Alerts:** an HTTPS failure that looks like token auth (401/403, `Authentication failed`, `Invalid username or password`, `Permission to ... denied`) adds `https_auth_fail=1` to the PUSH line; `feed-run.sh` records `last_push_auth_fail` / `push_auth_state` in `status.json` and prints `ALERT grok-feed push token auth failed ...` once per incident and `ALERT grok-feed push token auth recovered ...` when HTTPS works again; the 30-minute feed wake relays ALERT lines to Jeff. `feed-run.sh` also prints one `ALERT grok-feed GROK_FEED_GH_TOKEN expires ...` when `GROK_FEED_TOKEN_EXPIRES_UTC` is 14 days away. **Renewal reminder:** Grok Bot routine "Grok feed token renewal reminder" (id `grok-feed-token-renewal-reminder`) messages Jeff Fri Feb 5 and Mon Feb 15, 2027 at 9:00 AM ET. **Revoke:** GitHub (Jeff's account) -> Settings -> Developer settings -> Personal access tokens -> Fine-grained tokens -> this token -> Revoke; then remove the variable from the box env (the feed fails closed and rows stay local). **Before Feb 19, 2027:** Jeff regenerates or replaces it with the same scope (repo only, Contents read/write), Keela updates the box env and `GROK_FEED_TOKEN_EXPIRES_UTC` via a keela/ PR; otherwise HTTPS pushes fail on auth (ALERT) and rows stay local until the token is replaced. | Jeff (created on GitHub); Keela consumes it on the box |
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

## Incident note — 2026-11-26 (Budzilla)

The Grok box rebooted twice overnight (02:01 / 06:33 ET) and the
platform dropped secret injection into the box shell environment: all
five box secrets (the pool's ODDS_API_KEY, TELEGRAM_BOT_TOKEN,
HEALTHCHECK_URL and the feed's GROK_FEED_GH_TOKEN, GROK_FEED_HC_URL)
were absent until Jeff re-entered the pool three plus the feed token
via secret-request cards at 09:17–09:19 ET. The fallback file
/home/box/agent-data/box-secrets.json is owned 0600 by sand-host, so
its fallback reads fail after a platform reboot — do not rely on it.
GROK_FEED_HC_URL is still unset; Budzilla verified 2026-11-26 that
Jeff's Healthchecks account holds no feed check, so there may be no
URL to restore (create the check, or retire the variable — Jeff's
call; see the indy-pool hardening review). During the outage the feed
fell back to the SSH deploy-key push and GitHub rejected it; the repo
side is verified healthy (the "keela-box grok lane" deploy key is
present and writable, fingerprint
SHA256:VDidiPdjyfGpSxfmk0Db+YxNimgFJcV3xcvgAnHrpEk), so the failure is
in the box-side transport (core.sshCommand / ssh_proxy.py / key
offering). Full record: indy-pool
docs/incidents/2026-11-26-box-secrets-injection.md.

Follow-up, approved 2026-11-26 (R8 and R7 option A): the SSH fallback described
above is retired. A missing `GROK_FEED_GH_TOKEN` fails the push outright
(`PUSH fail reason=GROK_FEED_GH_TOKEN_unset`); there is no SSH attempt and no
monthly SSH drill, because Pingora rejects SSH CONNECT to ssh.github.com:443
with HTTP 400. If `GROK_FEED_HC_URL` is unset or empty, `lanes/grok/feed-run.sh`
reads `/workspace/grok-feed/state/.hc_ping_url` (mode 0600, box-owned, trailing
whitespace stripped) and never prints or logs the URL. The env var wins when
it is set.

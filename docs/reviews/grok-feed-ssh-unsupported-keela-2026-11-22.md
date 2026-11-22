# Grok feed: SSH from the box is unsupported (xAI T-K97957)

Prepared by Keela, Sun Nov 22, 2026, 3:00 PM ET. All times ET (UTC-5) unless marked UTC.
Companion matrix proposal: `daboodah-oss/ai-build-standards` `docs/reviews/capability-matrix-ssh-unsupported-keela-2026-11-22.md`.
Related: HTTPS fallback PR #12 (`9db5226`), root-cause PR #13, handoff PR #14 (`docs/reviews/grok-feed-https-fallback-handoff-keela-2026-11-22.md`).
No secret values and no gift data are in this file.

## The ruling

Jeff wrote xAI support Sat Nov 21, 2026, 7:02 PM ET about SSH to `ssh.github.com:443` through the box proxy (`CONNECT` 200, then `Connection closed by UNKNOWN port 65535`). HTTPS to GitHub was fine. Outages: Mon Nov 16 ~1:46 PM ET to 3:08 AM ET Tue Nov 17, and Sat Nov 21 from 3:06 PM ET.

Sam from SpaceXSI replied Sat Nov 21, 7:07 PM ET, ticket **T-K97957**, verbatim:

> SSH isn't supported from the Grok Bot computer right now. The computer only allows secure web (HTTPS) connections out, so SSH sessions can time out or drop. This is a current limitation, not something on your account or settings, and we can't open a port or add an allow-list entry on the computer to change it. Updating or resetting the computer won't help either, so there's no need to reset it. For GitHub, the supported alternative is Grok Bot's built-in GitHub connector. If your feed can go through the connector instead of SSH, that's the way to go.

Jeff replied Sun Nov 22, 2:46 PM ET acknowledging the ruling and saying he will look into the connector.

## What this means

- SSH from the box is **unsupported by design**, not flaky and not an account or settings problem. A reset will not fix it. xAI will not allow-list SSH.
- That explains the feed stalls in the root-cause and handoff docs: the proxy can answer `CONNECT` and then drop the tunnel, so an SSH-only push fails while readings and HTTPS keep working.
- The working path is already in place: the HTTPS fallback merged in **PR #12** (commit `9db5226`, Jeff approved Sat Nov 21, 7:00 PM ET). When the SSH push fails and `GROK_FEED_GH_TOKEN` is set, `lanes/grok/push_feed.py` pushes the same commit over HTTPS to `https://github.com/daboodah-oss/assistant-usage.git` `HEAD:main`, never forced. Token handling is unchanged: the value reaches git only through the environment (credential helper via `GIT_CONFIG_*` env vars); it is never in a URL, `.git/config`, argv, a file, a log, or a commit.
- This does **not** change lock behavior, the append-only / byte-prefix guards, or the "never force-push" rule.

## Live evidence (box state, Sun Nov 22, 2026)

Read from `/workspace/grok-feed/state/status.json` and `status.log`. No secrets are recorded here.

- `last_status=OK`, `consecutive_fail=0`, last OK at 2:42:56 PM ET (`last_ok_utc=2026-11-22T19:42:56+00:00`).
- After the token write-permission fix, **19 consecutive successful wakes** from 5:09 AM ET through 2:09 PM ET published with `via=https_fallback` and `ssh_err=and_the_repository_exists.` (the truncated SSH failure; expected under this ruling).
- The 2:42 PM ET run reported `PUSH ok sha=264ed0d108b681c56d2a315cb45b84e2ea794233 rows=3 bytes=483 attempt=1` with **no** `via=https_fallback` tag, which is the SSH-success code path in `push_feed.py`. That does not change the ruling: Sam said sessions can time out or drop. HTTPS remains the reliable path.

## Built-in GitHub connector (noted, not adopted now)

Sam's supported alternative is Grok Bot's built-in GitHub connector. It is a real option, but it is not a drop-in for this feed:

- The feed runs **unattended** in box routines via `lanes/grok/feed-run.sh` → `push_feed.py`. It is a scripted git cycle (fetch, reset, guards, commit, push), not an interactive agent turn.
- A connector path would mean a rewrite that goes through an AI wake to perform the push, instead of the existing script. That is a larger contract change: timing, failure handling, and the append-only guards would have to be re-expressed in a connector workflow.
- The fine-grained-token HTTPS fallback already works unattended and is scoped to `daboodah-oss/assistant-usage` only (Contents: Read and write). It expires Fri Feb 19, 2027, 8:44 PM ET (documented in the PR #14 handoff and `docs/SECRETS.md`).

The connector stays an option if Jeff wants to retire the token later. It is not the next step unless he asks for that rewrite.

## Option 3 — HTTPS primary (NOT implemented, needs Jeff's explicit OK)

Every wake still tries SSH first, waits for the expected failure, then falls back to HTTPS. Making HTTPS the main path (or the only path) would cut that failure and the noise it adds. This is a behavior change, so it needs Jeff's OK and a BEFORE/AFTER before any code lands. **Not implemented in this PR.**

Inspected read-only from origin/main: `lanes/grok/feed-run.sh` and `lanes/grok/push_feed.py` (also the box copies under `/workspace/assistant-usage-clone/lanes/grok/`, which matched those line numbers).

### BEFORE (current order)

1. `feed-run.sh` lines 27–28, 92–94: fetch uses HTTPS (`remote.origin.url`), but push is configured over SSH (`remote.origin.pushurl=ssh://git@ssh.github.com:443/daboodah-oss/assistant-usage.git`) with `core.sshCommand` (deploy key + `ssh_proxy.py`).
2. `feed-run.sh` lines 189–193: the run calls `push_feed.py` (or `--dry-run --probe-push`).
3. `push_feed.py` `main()`, after a successful `cycle()` commit (guards unchanged):
   - Line 172: SSH attempt first — `git push --porcelain origin HEAD:main` (uses the SSH pushurl; 120s timeout).
   - Lines 173–175: if that returns 0, print `PUSH ok sha=... rows=... bytes=... attempt=N` with no `via=` tag.
   - Lines 178–185: if SSH fails and `GROK_FEED_GH_TOKEN` is set, call `https_push()` (lines 54–66) — `git push --porcelain` to `REPO_HTTPS` `HEAD:main` with the env credential helper. Success prints `PUSH ok ... via=https_fallback ssh_err=...`.
   - Token unset = SSH only, same as before PR #12.
4. `--dry-run --probe-push` (lines 163–167) currently probes the SSH `origin` pushurl, not HTTPS.

### AFTER — two variants (choose at approval; neither is done)

**Variant A — HTTPS first, SSH remains a fallback.** In `push_feed.py` `main()`, try `https_push()` first when the token is set; only if HTTPS fails, try `git push origin HEAD:main` (SSH). The PUSH line should say `via=https` on the primary path and `via=ssh_fallback` if SSH is used. `--probe-push` should probe HTTPS. `feed-run.sh` can keep the SSH pushurl / `core.sshCommand` setup for that fallback. Token-unset behavior should be stated in the implementing PR (fail closed vs. SSH-only).

**Variant B — HTTPS only; SSH removed from the push path.** `main()` uses `https_push()` only. A real push requires the token; if it is unset, `PUSH fail` (fail closed). `feed-run.sh` can stop setting `remote.origin.pushurl` and `core.sshCommand` for this lane (fetch stays HTTPS). `--probe-push` probes HTTPS. SSH config and `ssh_proxy.py` are no longer on the feed push path.

### WHY

Sam's ruling is that SSH is unsupported, not temporarily broken. Keeping an unsupported protocol as the primary path adds a predictable failure (and up to 120s) on every wake, and it clutters `status.log` with `ssh_err=...`. HTTPS is the supported egress and is already the path that has been publishing the feed.

### What would change

- `lanes/grok/push_feed.py` (order or removal of the SSH push in `main()`; docstring; `--probe-push`; PUSH `via=` tags).
- `lanes/grok/feed-run.sh` (header comment still says "git over the deploy key"; variant B would also drop the SSH pushurl / `sshCommand` setup).
- `docs/SECRETS.md` and/or the feed alert path, if the renewal reminder and expiry/auth-failure alert below are included in the same change.

### What stays

- The feed lock (`flock` on `feed.lock` in `feed-run.sh`).
- The append-only / byte-prefix / single-path / no-token-like-material guards in `cycle()`.
- Never force-push; commits only `data/grok/usage.csv`.
- Token handling rules: the token is never in a URL, `.git/config`, argv, a file, a log, or a commit; credential helper via `GIT_CONFIG_*` only; output is scrubbed.
- Full-cycle retry (fetch → reset → guards → commit → push) and local-CSV-is-source-of-truth.

### Test plan

- A real (non-dry-run) feed run that appends rows and reports `PUSH ok` with the new `via=` tag and a commit SHA on origin/main.
- Confirm origin/main `data/grok/usage.csv` is byte-for-byte equal to the local CSV after that push.
- `status.json` / `status.log` `last_line` records the new push mode (`via=https` or equivalent).
- `--dry-run --probe-push` succeeds against HTTPS (and does not push).
- Guards still reject a non-prefix CSV (dry-run is enough).
- Token-unset fail-closed (variant B, or A if that is the chosen behavior).

### Rollback

Revert the Option 3 PR. PR #12 SSH-first + `https_fallback` remains the known-good path.

### Risks

- Token expiry **Fri Feb 19, 2027, 8:44 PM ET** becomes the single point of failure, especially under variant B (no SSH backup). A **renewal reminder** and an **expiry / auth-failure alert** should ship with Option 3, not as a later follow-up.
- Variant A still spends time on SSH if HTTPS fails (for example if the token has expired). That delay is acceptable as a last-ditch path only if Jeff wants it.
- Do not "simplify" credential handling by putting the token in a remote URL or `.git/config`.

## Ask

1. Muse: fold the capability-matrix correction in the companion review (do not edit `standard.md` here).
2. Jeff: Option 3 is proposed only. No implementation without his explicit OK, including which variant (A or B).

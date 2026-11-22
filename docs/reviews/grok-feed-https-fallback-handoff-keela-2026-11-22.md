# Grok feed: HTTPS push fallback live, handoff for Budzilla

Prepared by Keela, Sun Nov 22, 2026, 5:20 AM ET. All times ET (UTC-5) unless marked UTC.
Root-cause detail: `docs/reviews/grok-feed-stall-rootcause-keela-2026-11-21.md`.
No secret values and no gift data are in this file.

## What stalled and why

1. **SSH push blocked through the box proxy (intermittent, outside our control).** The feed pushed
   only over SSH to `ssh.github.com:443`, tunnelled through the box's HTTP CONNECT egress proxy.
   At times the proxy answers the CONNECT and then closes the tunnel
   (`Connection closed by UNKNOWN port`), so every push fails while readings keep working.
   - Mon Nov 16: failing from 1:46 PM ET (just after a reboot); recovered on its own 3:08 AM ET Tue
     Nov 17 with nothing changed on the box.
   - Sat Nov 21: failing from 3:06 PM ET (no reboot) and **still failing as of the last test,
     Sun Nov 22, 5:09 AM ET** (`ssh_err=and_the_repository_exists.`).
   - Rows were never lost: they wait in the local CSV and publish on the next good push.
2. **Inherited lock (fixed).** A feed run that restarted the heartbeat/tracker passed its fd-8
   `flock` to those long-lived daemons, so every later wake SKIPped silently (Nov 16 ~1:46-5:10 PM
   ET; Fri Nov 20 8:44 PM to Sat 8:28 AM ET). Fixed Sat Nov 21, 8:25 AM ET with `8>&-` (PR #9).

## What changed

- **PR #12** (merge `9db5226f38c98bf4db24d249db769f021709e3ba`, Sat Nov 21 ~8:50 PM ET; Jeff
  approved 7:00 PM ET): `lanes/grok/push_feed.py` HTTPS fallback. If the SSH push fails and
  `GROK_FEED_GH_TOKEN` is set, the same commit is pushed to
  `https://github.com/daboodah-oss/assistant-usage.git` `HEAD:main`, never forced. The token reaches
  git only through the environment (credential helper via `GIT_CONFIG_*` env vars): never in argv,
  a URL, `.git/config`, a file, a log or a commit; output is scrubbed. All guards unchanged
  (byte-prefix, append-only, single path). PUSH line shows `via=https_fallback ssh_err=...`.
  Token unset = old behavior exactly. `docs/SECRETS.md` documents the secret.
- **PR #13** (merge `8d76066fc221887d3b46c21e7f8366eb746281e8`): the root-cause review doc.
- **Secret:** `GROK_FEED_GH_TOKEN`, box environment only. GitHub fine-grained token,
  repository access only `daboodah-oss/assistant-usage`, permission Contents: Read and write.
  Expires Fri Feb 19, 2027, 8:44 PM ET. Revoke path is in `docs/SECRETS.md`.

## Token-permission miss

- The first token (Sat Nov 21 evening) did not have Contents: write. The setup check (repo API
  returns 200) passed only because the repo is **public**, so any token can read it.
- Caught by the box test at 8:48 PM ET and the 9:15 PM ET scheduled wake: the fallback ran,
  authenticated as daboodah-oss, and GitHub answered 403 ("Permission to ... denied"; API probe:
  "Resource not accessible by personal access token"). 16 wakes from 9:15 PM to 4:46 AM ET failed
  the same way; rows stayed safe locally. (The connector bridge commit `f506128` at ~8:51 PM ET
  had published everything up to 8:48 PM ET.)
- Jeff edited the token to Contents: Read and write, Sun Nov 22 ~5:08 AM ET.
- **Lesson:** verify the exact permission the job needs, not just access. Probe write with a
  non-mutating call (e.g. `POST /git/refs` with an all-zero sha: 422 = write allowed, 403 = not).

## Verification (Sun Nov 22, 2026)

- 5:08 AM ET write probe: **422 "Object does not exist"** (write accepted; was 403 at 9:18 PM ET Sat).
- 5:09 AM ET feed run via the normal path (`feed-run.sh` from origin/main, code `696dae874`):
  `PUSH ok sha=834e01355016c9a28f76e396a23be60e30a3b823 rows=53 bytes=8100 attempt=1 via=https_fallback ssh_err=and_the_repository_exists.`
- origin/main `data/grok/usage.csv` is **byte-for-byte equal** to the local CSV (sha256 prefix
  `6d7ecdef2d47f2d2`), diff +53 / -0, newest row `2026-11-22T10:09:01+00:00` (5:09 AM ET), and it
  includes 42 rows after the weekly reset (2026-11-22T02:41:26Z, 9:41 PM ET Sat).
- `status.json`: `last_status=OK`, `consecutive_fail=0`, `last_ok_utc=2026-11-22T10:09:03+00:00`.
- First scheduled wake after the fix: 5:15:59 AM ET (code `2d34b0add`):
  `PUSH ok sha=c36f36d6879d1dc26428a366f88b2016aefc5b18 rows=3 bytes=483 attempt=1 via=https_fallback ssh_err=and_the_repository_exists.`
  origin/main CSV again byte-equal to local after it.

## Still open (proposed, NOT approved; each needs Jeff's own-words OK)

1. Log SKIP runs to `status.log` and alert when the feed lock is held more than 1 hour.
2. Alert at the 2nd consecutive failed run, then every 6th (no re-ping flood).
3. Healthchecks watchdog for the feed (`GROK_FEED_HC_URL`, period ~30 min, grace ~75 min); every
   run today shows `hc=unset`.
4. Untruncated push reason: the https part of a failure is cut at 100 chars, which hid the `403`.
5. The SSH path itself is still blocked by the proxy; the feed now rides HTTPS until it recovers.

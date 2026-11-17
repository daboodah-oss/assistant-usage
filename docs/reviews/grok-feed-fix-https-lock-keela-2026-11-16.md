# Grok feed fix review: HTTPS push fallback + lock leak (pending Jeff review)

**Status: PENDING JEFF REVIEW. Nothing in this doc is active.** No script, config or box file
has been changed. The code below goes in only after Jeff approves it in his own words in chat,
as a separate `keela/` PR that changes exactly the lines shown here.

Prepared by Keela, Mon Nov 16, 2026, about 9:45 PM ET. All times ET unless marked UTC.
Design of record: `docs/reviews/grok-feed-design-keela-rev3-2026-11-15.md` (Jeff's Nov 15 ruling:
"Deploy key if SSH works, otherwise a fine-grained token over HTTPS").

## 1. What stopped (facts, checked Nov 16)

- Last commit of `data/grok/usage.csv` on `main`: `grok: sample 2026-11-16T18:07:25+00:00`
  (1:07 PM ET). The box rebooted at about 1:42 PM ET.
- **1:46 PM ET:** first run after the reboot failed at the push step with the same error as every
  failure since (`push_rejected ... and the repository exists`, after 3 attempts).
- **3:11 to 4:40 PM ET:** every run printed `GROK_FEED SKIP reason=another_run_holds_lock`. Cause:
  a feed run restarted the heartbeat and the usage tracker while it held the run lock, and both
  long-lived daemons inherited the lock's file descriptor (fd 8), so the lock never released.
  Fixed by hand at about 5:08 PM ET by restarting both daemons with fd 8 closed. No readings were
  taken on these runs, so these readings do not exist anywhere.
- **5:10 PM ET onward:** every run takes its reading and then fails at the push. Since the reboot,
  the box egress proxy answers `200` to `CONNECT ssh.github.com:443` (and `github.com:22`) and
  then closes the tunnel (`kex_exchange_identification: Connection closed`), so SSH, and with it
  the deploy key, cannot reach GitHub. HTTPS to github.com works (fetch is fine). The deploy key
  itself is unchanged. `feed-run.sh` has no HTTPS push path today.
- **Correction to what was reported earlier today:** the failed runs did *not* lose their
  readings. `push_feed.py` never touches the local lane CSV; on a failed push only the transport
  clone is reset. The local CSV currently holds 40 unpushed rows (10 readings: 1:45 PM, then
  5:10 PM to 9:15 PM ET), and `origin/main`'s CSV is still a byte-for-byte prefix of it (checked
  9:40 PM ET). The first successful push will publish all of them in one append-only commit.

## 2. Change 1: close the lock fd in long-lived children (lock leak)

**Location:** `lanes/grok/feed-run.sh`, step 4 (box bootstrap), lines 120 and 128.

The lock is taken at line 84-85 (`exec 8>"$STATE/feed.lock"` / `flock -n 8`). Every child the
script starts inherits fd 8. Short-lived children (git, python, curl) exit before the run ends,
so they are harmless. Only two paths can start daemons that outlive the run:
`/workspace/ops/box-bootstrap.sh` (which may `nohup setsid` `heartbeat.sh` and the tracker's
`start.sh`) and the direct tracker restart in the `--no-bootstrap` branch.

BEFORE (line 120):
```bash
  bl=$(timeout 60 bash "$BOOTSTRAP" 2>/dev/null | tail -n1)
```
AFTER:
```bash
  bl=$(timeout 60 bash "$BOOTSTRAP" 2>/dev/null 8>&- | tail -n1)
```

BEFORE (line 128):
```bash
    add "tracker=not_running"; [ $DRY = 0 ] && setsid nohup bash "$TRACKER_DIR/start.sh" >/dev/null 2>&1 < /dev/null & }
```
AFTER:
```bash
    add "tracker=not_running"; [ $DRY = 0 ] && setsid nohup bash "$TRACKER_DIR/start.sh" >/dev/null 2>&1 < /dev/null 8>&- & }
```

**WHY:** daemons started by a feed run must not hold the feed lock, or every later run SKIPs
until someone restarts them by hand (what happened 3:11 to 4:40 PM ET).

No other line changes. `bash -n` passes on the patched script.

## 3. Change 2: HTTPS push fallback with a fine-grained token

**Location:** `lanes/grok/push_feed.py` only. `feed-run.sh` is unchanged by this change: its
status line already embeds the whole `PUSH ...` line as `push=[...]`, so `transport=ssh|https`
shows up in `status.log` and `status.json` automatically. `remote.origin.pushurl` stays SSH.

**Behaviour:**
1. Push over SSH with the deploy key exactly as today.
2. If that push fails **without** a ref-level rejection (`[rejected]` / `[remote rejected]`, i.e.
   GitHub could not be reached or authenticated) **and** the token file exists, is non-empty and
   has no group/other permission bits (mode 600), push the same commit over HTTPS to
   `https://github.com/daboodah-oss/assistant-usage.git`.
3. The token is read from the file by a git credential helper only when git asks for it. It is
   never in argv, a URL, the remote config, a log, the status line or a commit. Any push output
   is passed through the existing token-pattern regex (`SECRET_RX`) and redacted before printing.
4. A ref-level rejection (someone else pushed first) is *not* a transport failure: no fallback;
   the existing full-cycle retry (fetch, reset, guards, commit) handles it, as today.
5. Unchanged: never forced, 3 full-cycle attempts, byte-prefix guard, append-only/numstat guard,
   newline guard, single-path guard, token-in-appended-bytes guard, commit message format.
6. The `PUSH` line gains `transport=ssh`, `transport=https`, or
   `transport=ssh(https_fallback=no_token)` when SSH failed and no usable token file exists.
   `--dry-run --probe-push` probes the same SSH-then-HTTPS path (`git push --dry-run`).

**Token (Jeff creates it; Keela never sees it in chat):**
- Created by Jeff on GitHub: fine-grained personal access token, resource owner
  `daboodah-oss`, repository access **only** `daboodah-oss/assistant-usage`, permissions
  **Contents: Read and write** (Metadata: read is added by GitHub automatically), nothing else.
  Expiry of Jeff's choosing (90 days suggested; the feed reports `https_fallback=no_token` or a
  push failure when it lapses).
- Entered through a **masked form**, never in chat, email or a repo file. Keela writes it to
  `~/.config/grok-feed/github_token` on the box (directory mode 700, file mode 600, outside any
  repo). Override path: env `GROK_FEED_TOKEN_FILE`. `docs/SECRETS.md` gets a row for it in the
  same PR (name, scope, location, how to revoke: GitHub Settings -> Developer settings ->
  Fine-grained tokens).

**Exact change (unified diff against `lanes/grok/push_feed.py` at `main`):**

```diff
@@ -13,7 +13,11 @@
      blob is byte-identical to the local file (no eol conversion).
   4. the appended bytes contain no token-like material.
 The staged diff is the only change check (no .last_pushed_sha). Every git call is
-non-interactive with a timeout. On final failure the rows stay in the local CSV and the
+non-interactive with a timeout. Push transport: SSH deploy key first; if that push fails without
+a ref-level rejection (i.e. GitHub could not be reached or authenticated) and the token file
+exists with mode 600, the same commit is pushed over HTTPS with a fine-grained token read from
+that file by a git credential helper at push time (never in argv, URLs, logs or commits).
+The PUSH line records transport=ssh|https. On final failure the rows stay in the local CSV and the
 next run retries. --dry-run does everything except the push (optionally probing auth with
 `git push --dry-run`), then resets the clone.
 Prints one line starting with PUSH. Exit 0 = ok/noop/dry-run, 1 = fail.
@@ -24,15 +28,20 @@
 ENV = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="/bin/false", LC_ALL="C")
 SECRET_RX = re.compile(rb"(eyJ[\w-]{10,}\.[\w-]{10,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_\w{20,}|"
                        rb"-----BEGIN [A-Z ]*PRIVATE KEY|[Bb]earer\s+[A-Za-z0-9._\-]{20,}|xai-[A-Za-z0-9]{20,})")
+REPO_HTTPS = "https://github.com/daboodah-oss/assistant-usage.git"
+TOKEN_FILE = os.environ.get("GROK_FEED_TOKEN_FILE", os.path.expanduser("~/.config/grok-feed/github_token"))
+# Reads the token from $GROK_FEED_TOKEN_FILE only when git asks; nothing token-shaped is in argv.
+CRED_HELPER = ('!f() { test "$1" = get || exit 0; echo username=x-access-token; '
+               'printf "password=%s\\n" "$(cat "$GROK_FEED_TOKEN_FILE")"; }; f')
 
 
 class Fail(Exception):
     pass
 
 
-def git(clone, *args, timeout=90, check=True):
+def git(clone, *args, timeout=90, check=True, env=None):
     try:
-        r = subprocess.run(["git", "-C", clone, *args], capture_output=True, timeout=timeout, env=ENV)
+        r = subprocess.run(["git", "-C", clone, *args], capture_output=True, timeout=timeout, env=env or ENV)
     except subprocess.TimeoutExpired:
         raise Fail("git %s timed out after %ss" % (args[0], timeout))
     if check and r.returncode != 0:
@@ -41,6 +50,32 @@
     return r
 
 
+def token_ok():
+    try:
+        st = os.stat(TOKEN_FILE)
+    except OSError:
+        return False
+    return st.st_size > 0 and (st.st_mode & 0o077) == 0
+
+
+def push_head(clone, dry=False):
+    """Push HEAD to main: SSH first, HTTPS token fallback on a transport failure.
+    Returns (rc, transport, last_output_line). Never forced; output is redacted."""
+    flags = ["--dry-run"] if dry else []
+    r = git(clone, "push", *flags, "--porcelain", "origin", "HEAD:main", timeout=120, check=False)
+    out = SECRET_RX.sub(b"<redacted>", r.stdout + r.stderr).decode("utf-8", "replace").strip()
+    ref_rejected = "[rejected]" in out or "[remote rejected]" in out
+    if r.returncode == 0 or ref_rejected:
+        return r.returncode, "ssh", (out.splitlines() or [""])[-1]
+    if not token_ok():
+        return r.returncode, "ssh(https_fallback=no_token)", (out.splitlines() or [""])[-1]
+    env = dict(ENV, GROK_FEED_TOKEN_FILE=TOKEN_FILE)
+    r = git(clone, "-c", "credential.helper=", "-c", "credential.helper=" + CRED_HELPER,
+            "push", *flags, "--porcelain", REPO_HTTPS, "HEAD:main", timeout=120, check=False, env=env)
+    out = SECRET_RX.sub(b"<redacted>", r.stdout + r.stderr).decode("utf-8", "replace").strip()
+    return r.returncode, "https", (out.splitlines() or [""])[-1]
+
+
 def newest_ts(data):
     for line in reversed(data.rstrip(b"\r\n").splitlines()):
         f = line.split(b",", 1)[0].strip()
@@ -125,20 +160,18 @@
         if a.dry_run:
             probe = ""
             if a.probe_push:
-                r = git(a.clone, "push", "--dry-run", "--porcelain", "origin", "HEAD:main", timeout=90, check=False)
-                out = (r.stdout + r.stderr).decode("utf-8", "replace").strip().splitlines()
-                probe = " probe_push=%s(%s)" % ("ok" if r.returncode == 0 else "fail",
-                                                 (out[-1] if out else "").replace(" ", "_")[:120])
+                prc, tr, last = push_head(a.clone, dry=True)
+                probe = " probe_push=%s(%s) transport=%s" % ("ok" if prc == 0 else "fail",
+                                                             last.replace(" ", "_")[:120], tr)
             stat = git(a.clone, "show", "--stat", "--format=%s", "HEAD").stdout.decode().strip().splitlines()
             git(a.clone, "reset", "--quiet", "--hard", "origin/main", check=False)
             print("PUSH dry-run would_commit=%r rows=%d bytes=%d stat=%r%s%s"
                   % (msg, rows, nbytes, stat[-1].strip() if stat else "", probe, crw)); return 0
-        r = git(a.clone, "push", "--porcelain", "origin", "HEAD:main", timeout=120, check=False)
-        if r.returncode == 0:
+        prc, tr, last = push_head(a.clone)
+        if prc == 0:
             sha = git(a.clone, "rev-parse", "HEAD").stdout.decode().strip()
-            print("PUSH ok sha=%s rows=%d bytes=%d attempt=%d%s" % (sha, rows, nbytes, attempt, crw)); return 0
-        out = (r.stderr or r.stdout).decode("utf-8", "replace").strip().splitlines()
-        err = "push rejected: " + (out[-1] if out else "")[:200]
+            print("PUSH ok sha=%s rows=%d bytes=%d attempt=%d transport=%s%s" % (sha, rows, nbytes, attempt, tr, crw)); return 0
+        err = "push rejected (transport=%s): %s" % (tr, last[:200])
         time.sleep(5 * attempt)
     git(a.clone, "reset", "--quiet", "--hard", "origin/main", check=False)
     print("PUSH fail reason=%s attempts=%d" % ((err or "unknown").replace(" ", "_")[:300], a.attempts)); return 1
```

**WHY:** Jeff's Nov 15 ruling named an HTTPS fine-grained token as the fallback when SSH does
not work; since the 1:42 PM ET reboot SSH does not work, and the script has no HTTPS path.

## 4. Optional, separate decision: keep unpushed rows locally

**Not needed; no change proposed.** I had suggested this because I believed failed runs dropped
their readings. They do not (section 1): the local lane CSV keeps every row, and the next good
push publishes the backlog append-only. The only real loss today was the 3:11 to 4:40 PM ET
window, where no reading was taken at all; Change 1 addresses that.

## 5. Test plan (after Jeff's OK)

Offline checks already done on a scratch copy (not the live script):
- Patched `push_feed.py` compiles; patched `feed-run.sh` passes `bash -n`.
- Local bare-repo simulation: SSH-path push succeeds and prints `transport=ssh`; with a dead
  pushurl and no token file it fails cleanly with `transport=ssh(https_fallback=no_token)` and
  pushes nothing; `--dry-run --probe-push` reports the same.
- The credential helper, fed a dummy value from a mode-600 file, answers `git credential fill`
  with `username=x-access-token` and that value; a mode-644 file is refused (`token_ok` false).

Rollout, in order:
1. Jeff approves in chat. Keela opens the `keela/` PR with exactly these two changes plus the
   `docs/SECRETS.md` row and a one-line README "Auth" note; merge after green checks and Jeff's OK.
2. Jeff creates the token; Keela stores it via the masked form (section 3). Nothing echoed.
3. **Dry run:** `feed-run.sh --dry-run` (loads code from `origin/main`). Expect
   `GROK_FEED DRYRUN ... probe_push=ok(...) transport=https` while SSH is blocked. Confirm no
   commit on `main`, the lane CSV unchanged, and no token-like text in the output or
   `status.log` (`grep -E 'github_pat_|ghp_'` finds nothing).
4. **One live run** on the next 30-minute wake (or a manual run). Expect `GROK_FEED OK` (or
   `WARN`) with `push=[PUSH ok sha=... rows=N ... transport=https]`, where N includes the backlog
   (40 rows as of 9:15 PM ET, plus new rows).
5. **Verify on `main`:** the commit `grok: sample <ts>` exists, touches only
   `data/grok/usage.csv`, deletes 0 lines, and the 1:07 PM ET commit's file is a byte prefix of
   the new one. The site build picks it up on its next run.
6. Lock fix check: after a run that restarts a daemon, `fuser`/`lsof` on `feed.lock` shows no
   process once the run exits, and the next wake is not a SKIP.
7. Two more consecutive OK runs, then one receipt to the ops-log branch.

Rollback: revert the PR (normal revert commit, never a force-push) and/or delete the token file
and revoke the token on GitHub; the feed then fails closed with rows kept locally, as today.

## 6. What this does not change

`check-export.py`, picks/ranks/tiebreakers/locked games/pool exports, the data contract, the
dashboard, `feed.conf`, the wake cadence, the comparison rule, account settings (X, Grok, xAI,
billing). No token or key material is in this doc or the repo.

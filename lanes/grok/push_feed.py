#!/usr/bin/env python3
"""Push the local Grok CSV to daboodah-oss/assistant-usage main via real git (R2).

Transport clone pattern (as lanes/muse/push_git.py): the LOCAL CSV is the source of truth;
the clone is only a vehicle. Up to 3 attempts, each a FULL cycle:
  fetch origin/main -> reset the clone to it -> guards -> copy CSV in -> stage ONLY
  data/grok/usage.csv -> commit -> push HEAD:main (never forced).
Guards (any failure pushes nothing and exits 1):
  1. byte-prefix (primary): origin/main's CSV must be a byte-for-byte prefix of the local
     CSV, so every byte already on main, line endings included, is unchanged.
  2. local CSV non-empty and ends in "\\n".
  3. staged diff deletes 0 lines (numstat), only that one path is staged, and the staged
     blob is byte-identical to the local file (no eol conversion).
  4. the appended bytes contain no token-like material.
The staged diff is the only change check (no .last_pushed_sha). Every git call is
non-interactive with a timeout. On final failure the rows stay in the local CSV and the
next run retries. --dry-run does everything except the real push (with --probe-push,
an HTTPS `git push --dry-run` when the token is set), then resets the clone.
HTTPS only (R8; Budzilla and Jeff, 2026-11-26). The SSH fallback and the monthly SSH
drill are retired: Pingora, the box egress proxy, rejects SSH CONNECT to ssh.github.com:443
with HTTP 400. Every real push goes to REPO_HTTPS HEAD:main (never forced) using
GROK_FEED_GH_TOKEN (fine-grained token, assistant-usage only, Contents r/w). A successful
PUSH line says via=https. If the token is unset or empty, the pusher prints
PUSH fail reason=GROK_FEED_GH_TOKEN_unset and exits 1 before any commit or push.
An HTTPS failure that looks like token auth (401/403, "Authentication failed",
"Invalid username or password", "Permission to ... denied", permission denied, bad
credentials) adds https_auth_fail=1 to the PUSH fail line; feed-run.sh turns that into
an ALERT once per incident. --dry-run --probe-push probes HTTPS when the token is set,
and reports probe_push=fail(GROK_FEED_GH_TOKEN_unset) when it is not (the dry-run itself
still exits 0 so the guards can be checked). The token reaches git only through the
environment: a credential helper set via GIT_CONFIG_* env vars expands $GROK_FEED_GH_TOKEN
inside git's own shell, so the value is never in argv, a URL, .git/config, a file, or any
output (all git output is scrubbed).
Prints one line starting with PUSH. Exit 0 = ok/noop/dry-run, 1 = fail.
"""
import argparse, os, re, shutil, subprocess, sys, time

REL = "data/grok/usage.csv"
TOKEN_VAR = "GROK_FEED_GH_TOKEN"
REPO_HTTPS = "https://github.com/daboodah-oss/assistant-usage.git"
ENV = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="/bin/false", LC_ALL="C")
ENV.pop(TOKEN_VAR, None)  # only the HTTPS push gets the token
# Credential helper text: references the variable by name; git's shell expands it at use time.
CRED_HELPER = '!f() { test "$1" = get || exit 0; echo username=x-access-token; echo "password=${%s}"; }; f' % TOKEN_VAR
SECRET_RX = re.compile(rb"(eyJ[\w-]{10,}\.[\w-]{10,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_\w{20,}|"
                       rb"-----BEGIN [A-Z ]*PRIVATE KEY|[Bb]earer\s+[A-Za-z0-9._\-]{20,}|xai-[A-Za-z0-9]{20,})")


class Fail(Exception):
    pass


def scrub(text):
    """Redact token-like material (and the token value itself) from git output."""
    b = text.encode("utf-8", "replace") if isinstance(text, str) else text
    tok = os.environ.get(TOKEN_VAR, "").encode()
    if tok:
        b = b.replace(tok, b"<scrubbed>")
    return SECRET_RX.sub(b"<scrubbed>", b).decode("utf-8", "replace")


AUTH_RX = re.compile(r"returned error: 40[13]|\b40[13]\b.*(Unauthorized|Forbidden)|Authentication failed|"
                     r"Invalid username or password|Permission to \S+ denied|[Pp]ermission denied|"
                     r"Bad credentials|could not read (Username|Password)|Resource not accessible")


def https_push(clone, dry_run=False):
    """Push HEAD:main over HTTPS with the token from the environment.
    Returns (rc, last_line, auth_fail). Output is scrubbed before it is inspected or returned."""
    env = dict(ENV, GIT_CONFIG_COUNT="2",
               GIT_CONFIG_KEY_0="credential.helper", GIT_CONFIG_VALUE_0="",
               GIT_CONFIG_KEY_1="credential.helper", GIT_CONFIG_VALUE_1=CRED_HELPER)
    env[TOKEN_VAR] = os.environ[TOKEN_VAR]
    cmd = ["git", "-C", clone, "push"] + (["--dry-run"] if dry_run else []) + ["--porcelain", REPO_HTTPS, "HEAD:main"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=120, env=env)
    except subprocess.TimeoutExpired:
        return 124, "https push timed out after 120s", False
    text = scrub((r.stderr or b"") + b"\n" + (r.stdout or b""))
    out = scrub(r.stderr or r.stdout).strip().splitlines()
    auth = r.returncode != 0 and bool(AUTH_RX.search(text))
    return r.returncode, (out[-1] if out else "")[:200], auth


def git(clone, *args, timeout=90, check=True):
    try:
        r = subprocess.run(["git", "-C", clone, *args], capture_output=True, timeout=timeout, env=ENV)
    except subprocess.TimeoutExpired:
        raise Fail("git %s timed out after %ss" % (args[0], timeout))
    if check and r.returncode != 0:
        msg = (r.stderr or r.stdout).decode("utf-8", "replace").strip().splitlines()
        raise Fail("git %s rc=%s: %s" % (args[0], r.returncode, (msg[-1] if msg else "")[:200]))
    return r


def newest_ts(data):
    for line in reversed(data.rstrip(b"\r\n").splitlines()):
        f = line.split(b",", 1)[0].strip()
        if f and f != b"timestamp_utc":
            return f.decode("ascii", "replace")
    return "unknown"


def cycle(a, src_bytes):
    clone = a.clone
    git(clone, "fetch", "--quiet", "origin", "main", timeout=90)
    git(clone, "reset", "--quiet", "--hard", "origin/main")
    git(clone, "clean", "-fdq", "--", os.path.dirname(REL))
    r = git(clone, "show", "origin/main:" + REL, check=False)
    remote = r.stdout if r.returncode == 0 else b""
    if not src_bytes:
        raise Fail("guard: local CSV is empty")
    if not src_bytes.endswith(b"\n"):
        raise Fail("guard: local CSV does not end in a newline")
    if len(src_bytes) < len(remote) or src_bytes[:len(remote)] != remote:
        # find first differing byte for the error
        n = next((i for i in range(min(len(remote), len(src_bytes))) if remote[i] != src_bytes[i]),
                 min(len(remote), len(src_bytes)))
        raise Fail("guard: origin/main CSV (%d bytes) is not a byte prefix of local (%d bytes); "
                   "first difference at byte %d" % (len(remote), len(src_bytes), n))
    added = src_bytes[len(remote):]
    if not added:
        return ("noop", None, 0, 0)
    if remote and not remote.endswith(b"\n"):
        raise Fail("guard: origin/main CSV does not end in a newline")
    if SECRET_RX.search(added):
        raise Fail("guard: appended bytes contain token-like material")
    dst = os.path.join(clone, REL)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "wb") as f:
        f.write(src_bytes)
    git(clone, "add", "--", REL)
    staged = git(clone, "diff", "--cached", "--name-only").stdout.decode().split()
    if staged != [REL]:
        raise Fail("guard: staged paths are %s, expected only %s" % (staged, REL))
    ns = git(clone, "diff", "--cached", "--numstat", "--", REL).stdout.decode().split("\t")
    if len(ns) < 2 or ns[1] != "0":
        raise Fail("guard: staged diff deletes %s lines" % (ns[1] if len(ns) > 1 else "?"))
    if git(clone, "show", ":" + REL).stdout != src_bytes:
        raise Fail("guard: staged blob differs from local bytes (line-ending conversion?)")
    rows = added.count(b"\n")
    cr_new = added.count(b"\r\n")
    msg = "grok: sample %s" % newest_ts(src_bytes)
    git(clone, "commit", "--quiet", "-m", msg, "-m",
        "feed-run (Grok feed redesign): +%d rows, +%d bytes, append-only + byte-prefix guard passed." % (rows, len(added)))
    return ("commit", msg, rows, len(added), cr_new)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clone", default=os.environ.get("GROK_FEED_CLONE", "/workspace/assistant-usage-clone"))
    ap.add_argument("--src", default=os.environ.get("GROK_FEED_CSV", "/workspace/assistant-usage/data/grok/usage.csv"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--probe-push", action="store_true", help="with --dry-run: HTTPS git push --dry-run to test auth")
    ap.add_argument("--attempts", type=int, default=3)
    a = ap.parse_args()
    if not os.path.isdir(os.path.join(a.clone, ".git")):
        print("PUSH fail reason=clone_missing path=%s" % a.clone); return 1
    if not os.path.exists(a.src):
        print("PUSH fail reason=local_csv_missing"); return 1
    err = None
    use_https = bool(os.environ.get(TOKEN_VAR))
    if not a.dry_run and not use_https:
        # R8: HTTPS only. Stop before any commit or push.
        print("PUSH fail reason=GROK_FEED_GH_TOKEN_unset detail=https_only_set_GROK_FEED_GH_TOKEN")
        return 1
    auth_fail = False
    for attempt in range(1, a.attempts + 1):
        with open(a.src, "rb") as f:
            src_bytes = f.read()
        try:
            res = cycle(a, src_bytes)
        except Fail as e:
            err = str(e)
            if err.startswith("guard:"):
                git(a.clone, "reset", "--quiet", "--hard", "origin/main", check=False)
                print("PUSH fail reason=%s" % err.replace(" ", "_")[:300]); return 1
            time.sleep(5 * attempt); continue
        if res[0] == "noop":
            print("PUSH noop reason=origin_main_already_has_local_bytes"); return 0
        _, msg, rows, nbytes, cr_new = res
        crw = " warn=new_crlf_rows:%d" % cr_new if cr_new else ""
        if a.dry_run:
            probe = ""
            if a.probe_push and use_https:
                hrc, hlast, hauth = https_push(a.clone, dry_run=True)
                probe = " probe_push=%s(%s) via=https%s" % ("ok" if hrc == 0 else "fail", hlast.replace(" ", "_")[:120],
                                                           " https_auth_fail=1" if hauth else "")
            elif a.probe_push:
                probe = " probe_push=fail(GROK_FEED_GH_TOKEN_unset)"
            elif not use_https:
                probe = " token=unset real_push=would_fail"
            stat = git(a.clone, "show", "--stat", "--format=%s", "HEAD").stdout.decode().strip().splitlines()
            git(a.clone, "reset", "--quiet", "--hard", "origin/main", check=False)
            print("PUSH dry-run would_commit=%r rows=%d bytes=%d stat=%r%s%s"
                  % (msg, rows, nbytes, stat[-1].strip() if stat else "", probe, crw)); return 0
        # R8: HTTPS only. A failed HTTPS push retries the full cycle.
        hrc, hlast, hauth = https_push(a.clone)
        auth_fail = auth_fail or hauth
        if hrc == 0:
            sha = git(a.clone, "rev-parse", "HEAD").stdout.decode().strip()
            print("PUSH ok sha=%s rows=%d bytes=%d attempt=%d via=https%s" % (sha, rows, nbytes, attempt, crw)); return 0
        err = "push rejected: " + hlast[:200]
        time.sleep(5 * attempt)
    git(a.clone, "reset", "--quiet", "--hard", "origin/main", check=False)
    reason = scrub(err or "unknown").replace(" ", "_").replace("\n", "_")[:300]
    print("PUSH fail reason=%s attempts=%d%s" % (reason, a.attempts,
                                                " https_auth_fail=1" if auth_fail else "")); return 1


if __name__ == "__main__":
    sys.exit(main())

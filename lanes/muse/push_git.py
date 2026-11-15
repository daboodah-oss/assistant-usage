#!/usr/bin/env python3
"""Push data/muse/usage.csv to daboodah-oss/assistant-usage via real git.

Replaces the old gh.py push-file upload (Contents API, whole file every
run, hard 1 MB ceiling). Git transport sends only the changed bytes.

The clone at ~/workspace/assistant-usage-clone is a transport vehicle
only: the workspace CSV (written by collect.py) is the source of truth.
Each run re-syncs the clone to origin/main, copies the CSV in, commits
if it changed, and pushes — retrying the whole sequence on a
non-fast-forward rejection (other lanes commit to main too).

Auth: a repo-scoped deploy key (write, this repo only) at
~/.ssh/assistant_usage_deploy, used via the clone's core.sshCommand.
This VM's egress proxy resets direct SSH, so the key talks to
ssh.github.com:443 through an HTTP CONNECT tunnel
(lanes/muse/ssh_proxy.py reads the proxy address/credentials from
the HTTPS_PROXY environment variable). HTTPS git with the stored
PAT is not an option: the credential service only swaps its
surrogate for the real token on api.github.com requests, and
GitHub rejects the surrogate itself for git operations.
"""
import os
import shutil
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
SRC = os.path.join(HOME, "workspace", "assistant-usage", "data", "muse", "usage.csv")
CLONE = os.path.join(HOME, "workspace", "assistant-usage-clone")
DST = os.path.join(CLONE, "data", "muse", "usage.csv")
ENV = dict(os.environ, GIT_TERMINAL_PROMPT="0")


def git(*args):
    return subprocess.run(["git", "-C", CLONE, *args],
                          capture_output=True, text=True, timeout=120, env=ENV)


def main():
    if not os.path.isdir(os.path.join(CLONE, ".git")):
        print(f"pusher: clone missing at {CLONE}", file=sys.stderr)
        return 1
    if not os.path.exists(SRC):
        print(f"pusher: source CSV missing at {SRC}", file=sys.stderr)
        return 1
    for attempt in range(1, 4):
        r = git("fetch", "origin", "main")
        if r.returncode != 0:
            print(f"pusher: fetch failed: {r.stderr.strip()[:200]}", file=sys.stderr)
            return 1
        git("reset", "--hard", "origin/main")
        shutil.copyfile(SRC, DST)
        git("add", "data/muse/usage.csv")
        if not git("status", "--porcelain").stdout.strip():
            print("pusher: unchanged, nothing to push")
            return 0
        r = git("commit", "-m", "Muse lane sample (auto)")
        if r.returncode != 0:
            print(f"pusher: commit failed: {r.stderr.strip()[:200]}", file=sys.stderr)
            return 1
        r = git("push", "origin", "main")
        if r.returncode == 0:
            sha = git("rev-parse", "--short", "HEAD").stdout.strip()
            print(f"pusher: pushed {sha}")
            return 0
        print(f"pusher: push attempt {attempt} rejected, retrying",
              file=sys.stderr)
        time.sleep(5)
    print("pusher: push failed after 3 attempts", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

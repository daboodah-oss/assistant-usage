#!/usr/bin/env python3
"""Retired 2026-11-26 (R8). The Grok lane pushes over HTTPS only.

Pingora rejects SSH CONNECT to ssh.github.com:443 with HTTP 400, so this
file is not a fallback and it does not open a tunnel. It remains so a
feed-run.sh from before that change can still load lanes/grok/ssh_proxy.py
from origin/main on its next wake (that script's code list is fixed until
the clone's copy is replaced). Delete this file only after the box is
running the feed-run.sh that no longer lists it. The muse lane has its
own proxy and is not affected.
"""
import sys

sys.stderr.write("ssh_proxy: retired 2026-11-26; Grok-lane pushes are HTTPS-only\n")
sys.exit(1)

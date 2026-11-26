#!/usr/bin/env python3
"""Offline tests for the HTTPS-only Grok pusher. No network, no real token.

    python3 lanes/grok/test_push_feed.py
"""
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import push_feed  # noqa: E402

TOKEN_VAR = push_feed.TOKEN_VAR
# Fixture value. Not a credential. The shape check builds a PAT-like string at runtime.
TOKEN = "test-token-value-not-a-credential"
PAT_PREFIX = "github" + "_pat_"
HEADER = b"timestamp_utc,usage_pct,plan,reset_iso,window,raw\n"
ROW = b"2026-01-01T00:00:00+00:00,1.0,Ultra,2026-01-08T00:00:00+00:00,weekly,test\n"
EXTRA = b"2026-01-01T00:30:00+00:00,2.0,Ultra,2026-01-08T00:00:00+00:00,weekly,test\n"


def git(cwd, *args):
    subprocess.check_call(["git", "-C", cwd, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_clone():
    tmp = tempfile.mkdtemp(prefix="grok-push-test-")
    bare = os.path.join(tmp, "bare.git")
    clone = os.path.join(tmp, "clone")
    subprocess.check_call(["git", "init", "--bare", "-q", "-b", "main", bare])
    subprocess.check_call(["git", "clone", "-q", bare, clone], stderr=subprocess.DEVNULL)
    git(clone, "config", "user.email", "grok-test@example.com")
    git(clone, "config", "user.name", "grok test")
    git(clone, "config", "core.autocrlf", "false")
    rel = os.path.join(clone, "data", "grok", "usage.csv")
    os.makedirs(os.path.dirname(rel))
    with open(rel, "wb") as f:
        f.write(HEADER + ROW)
    git(clone, "add", "--", "data/grok/usage.csv")
    git(clone, "commit", "-q", "-m", "base")
    git(clone, "push", "-q", "origin", "HEAD:main")
    git(clone, "fetch", "-q", "origin", "main")
    src = os.path.join(tmp, "local.csv")
    with open(src, "wb") as f:
        f.write(HEADER + ROW + EXTRA)
    return tmp, clone, src


class PushFeedTests(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get(TOKEN_VAR)
        os.environ.pop(TOKEN_VAR, None)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop(TOKEN_VAR, None)
        else:
            os.environ[TOKEN_VAR] = self._saved

    def run_main(self, argv):
        buf = io.StringIO()
        with patch.object(sys, "argv", argv), redirect_stdout(buf):
            rc = push_feed.main()
        return rc, buf.getvalue()

    def assert_no_token(self, text):
        if TOKEN in text:
            self.fail("token value leaked into output")

    def test_scrub_redacts_token_value_and_pat_shape(self):
        os.environ[TOKEN_VAR] = TOKEN
        shaped = PAT_PREFIX + ("b" * 24)
        out = push_feed.scrub("auth failed for " + TOKEN + " and " + shaped)
        if TOKEN in out or shaped in out:
            self.fail("scrub left a secret-shaped value in output")
        self.assertIn("<scrubbed>", out)

    def test_missing_and_empty_token_fail_before_git(self):
        tmp = tempfile.mkdtemp(prefix="grok-push-missing-")
        clone = os.path.join(tmp, "clone")
        os.makedirs(os.path.join(clone, ".git"))
        src = os.path.join(tmp, "usage.csv")
        with open(src, "wb") as f:
            f.write(HEADER + ROW)
        calls = []

        def boom(*_a, **_k):
            calls.append(1)
            raise AssertionError("git should not run when the token is absent")

        for value in (None, ""):
            with self.subTest(value=value):
                if value is None:
                    os.environ.pop(TOKEN_VAR, None)
                else:
                    os.environ[TOKEN_VAR] = value
                calls.clear()
                with patch.object(push_feed.subprocess, "run", boom):
                    rc, out = self.run_main(["push_feed.py", "--clone", clone, "--src", src])
                self.assertEqual(rc, 1)
                self.assertEqual(calls, [])
                self.assertEqual(
                    out.strip(),
                    "PUSH fail reason=GROK_FEED_GH_TOKEN_unset detail=https_only_set_GROK_FEED_GH_TOKEN",
                )
                self.assert_no_token(out)

    def test_https_push_keeps_token_out_of_argv_and_output(self):
        os.environ[TOKEN_VAR] = TOKEN
        captured = {}

        def fake_run(cmd, **kw):
            captured["cmd"] = list(cmd)
            captured["env"] = kw.get("env") or {}
            class R:
                returncode = 1
                stdout = b""
                stderr = b"Authentication failed for " + TOKEN.encode()
            return R()

        with patch.object(push_feed.subprocess, "run", fake_run):
            rc, last, auth = push_feed.https_push("/tmp/not-a-real-clone")
        joined = " ".join(captured["cmd"])
        if TOKEN in joined:
            self.fail("token value leaked into git argv")
        self.assertIn(push_feed.REPO_HTTPS, captured["cmd"])
        self.assertNotIn("ssh.github.com", joined)
        self.assertEqual(captured["env"].get(TOKEN_VAR), TOKEN)
        helper = captured["env"].get("GIT_CONFIG_VALUE_1", "")
        self.assertIn("${GROK_FEED_GH_TOKEN}", helper)
        self.assertNotIn(TOKEN, helper)
        self.assertNotIn(TOKEN, last)
        self.assertIn("<scrubbed>", last)
        self.assertTrue(auth)
        self.assertNotEqual(rc, 0)
        # The base git env used for fetch/commit must not carry the token.
        self.assertNotIn(TOKEN_VAR, push_feed.ENV)

    def _guard_pushes(self):
        real = push_feed.subprocess.run
        seen = []

        def wrapped(cmd, **kw):
            if isinstance(cmd, list) and cmd and cmd[0] == "git" and "push" in cmd:
                seen.append(list(cmd))
                raise AssertionError("git push ran outside https_push")
            return real(cmd, **kw)

        return seen, wrapped

    def test_https_failure_does_not_fall_back_to_ssh(self):
        _tmp, clone, src = make_clone()
        os.environ[TOKEN_VAR] = TOKEN
        seen, wrapped = self._guard_pushes()

        def fake_https(_clone, dry_run=False):
            return 1, "Authentication failed " + TOKEN, True

        with patch.object(push_feed.subprocess, "run", wrapped), \
             patch.object(push_feed, "https_push", fake_https), \
             patch.object(push_feed.time, "sleep"):
            rc, out = self.run_main([
                "push_feed.py", "--clone", clone, "--src", src, "--attempts", "1"])
        self.assertEqual(rc, 1)
        self.assertEqual(seen, [])
        self.assertIn("PUSH fail", out)
        self.assertIn("https_auth_fail=1", out)
        self.assertNotIn("ssh_fallback", out)
        self.assertNotIn("ssh.github.com", out)
        self.assert_no_token(out)

    def test_https_success_reports_via_https(self):
        _tmp, clone, src = make_clone()
        os.environ[TOKEN_VAR] = TOKEN
        seen, wrapped = self._guard_pushes()

        def fake_https(_clone, dry_run=False):
            return 0, "", False

        with patch.object(push_feed.subprocess, "run", wrapped), \
             patch.object(push_feed, "https_push", fake_https), \
             patch.object(push_feed.time, "sleep"):
            rc, out = self.run_main([
                "push_feed.py", "--clone", clone, "--src", src, "--attempts", "1"])
        self.assertEqual(rc, 0)
        self.assertIn("PUSH ok", out)
        self.assertIn("via=https", out)
        self.assertNotIn("ssh_fallback", out)
        self.assertEqual(seen, [])
        self.assert_no_token(out)

    def test_dry_run_probe_without_token_does_not_push(self):
        _tmp, clone, src = make_clone()
        os.environ.pop(TOKEN_VAR, None)
        seen, wrapped = self._guard_pushes()

        def fake_https(*_a, **_k):
            raise AssertionError("https_push called without a token")

        with patch.object(push_feed.subprocess, "run", wrapped), \
             patch.object(push_feed, "https_push", fake_https):
            rc, out = self.run_main([
                "push_feed.py", "--clone", clone, "--src", src, "--dry-run", "--probe-push"])
        self.assertEqual(rc, 0)
        self.assertIn("PUSH dry-run", out)
        self.assertIn("probe_push=fail(GROK_FEED_GH_TOKEN_unset)", out)
        self.assertEqual(seen, [])
        self.assert_no_token(out)

    def test_source_has_no_ssh_push_path(self):
        with open(push_feed.__file__, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("ssh_fallback", src)
        self.assertNotIn('"origin", "HEAD:main"', src)


if __name__ == "__main__":
    unittest.main()

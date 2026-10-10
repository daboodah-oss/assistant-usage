#!/usr/bin/env python3
"""Offline tests for collect.py (no network, no real tokens).  Run:
    python3 lanes/claude/test_collect.py
"""
import csv
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect  # noqa: E402

SAMPLE = {
    "five_hour": {"utilization": 37.0, "resets_at": "2026-10-10T18:00:00.123456+00:00"},
    "seven_day": {"utilization": 26, "resets_at": "2026-10-14T04:00:00Z"},
    "seven_day_opus": None,
    "limits": [
        {"kind": "weekly_model", "percent": 12.5, "resets_at": "2026-10-14T04:00:00Z",
         "scope": {"model": {"display_name": "Fable 5"}}},
        {"kind": "five_hour", "percent": 99, "resets_at": "2026-10-10T18:00:00Z"},
    ],
    "extra_usage": {"is_enabled": False},
}
ACCESS, REFRESH = "acc-SECRET-111", "ref-SECRET-222"
NEW = {"access_token": "acc-NEW", "refresh_token": "ref-NEW", "expires_in": 3600}
ENV_KEYS = ("CLAUDE_ACCESS_TOKEN", "CLAUDE_REFRESH_TOKEN", "CLAUDE_PLAN", "CLAUDE_TOKEN_OUT",
            "CLAUDE_NO_REFRESH", "CLAUDE_CREDENTIALS_FILE", "CLAUDE_CONFIG_DIR", "CLAUDE_USAGE_CSV")


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def write(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.csv = os.path.join(self.tmp, "data", "claude", "usage.csv")
        collect.CSV_PATH = self.csv
        collect.LOCK_PATH = os.path.join(self.tmp, "lock")
        collect.REFRESH_LOCK_WAIT_S = 0.2
        collect._SECRETS.clear()
        for k in ENV_KEYS:
            os.environ.pop(k, None)
        self.calls = []

    def script(self, usage_responses, refresh_response=None):
        usage_iter = iter(usage_responses)

        def fake_usage(tok):
            self.calls.append(("usage", tok))
            return next(usage_iter)

        def fake_refresh(rt):
            self.calls.append(("refresh", rt))
            return refresh_response

        collect.get_usage = fake_usage
        collect.refresh_tokens = fake_refresh

    def run_main(self):
        o, e = io.StringIO(), io.StringIO()
        with redirect_stdout(o), redirect_stderr(e):
            rc = collect.main()
        return rc, o.getvalue(), e.getvalue()

    def rows(self):
        if not os.path.exists(self.csv):
            return []
        with open(self.csv, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def assert_no_secrets(self, *texts):
        blob = "".join(texts) + (read(self.csv) if os.path.exists(self.csv) else "")
        for s in (ACCESS, REFRESH, "acc-NEW", "ref-NEW"):
            self.assertNotIn(s, blob)


class ParseTests(unittest.TestCase):
    def test_windows_and_order(self):
        rows = collect.parse_usage(SAMPLE)
        self.assertEqual([r[0] for r in rows], ["five_hour", "weekly_fable_5", "seven_day"])
        d = {r[0]: r for r in rows}
        self.assertEqual(d["five_hour"][1], 37.0)  # flat key wins over limits[] fallback
        self.assertTrue(d["seven_day"][2].endswith("+00:00"))

    def test_zero_is_kept_not_dropped(self):
        rows = collect.parse_usage({"five_hour": {"utilization": 0, "resets_at": None},
                                    "seven_day": {"utilization": 0.0}})
        self.assertEqual([(r[0], r[1], r[2]) for r in rows],
                         [("five_hour", 0, ""), ("seven_day", 0.0, "")])

    def test_bad_values_are_skipped_not_guessed(self):
        bad = {"five_hour": {"utilization": "37"}, "seven_day": {"utilization": True},
               "limits": [{"percent": 150, "scope": {"model": {"display_name": "X"}}},
                          {"percent": None, "scope": {"model": {"display_name": "Y"}}}, "junk"]}
        self.assertEqual(collect.parse_usage(bad), [])

    def test_unrecognized_shapes(self):
        for js in (None, [], "x", {}, {"error": "nope"}, {"five_hour": 5}):
            self.assertEqual(collect.parse_usage(js), [], js)

    def test_limits_fallback_when_flat_missing(self):
        rows = collect.parse_usage({"limits": [{"kind": "seven_day", "percent": 40,
                                                "resets_at": "2026-10-14T04:00:00Z"}]})
        self.assertEqual([(r[0], r[1]) for r in rows], [("seven_day", 40)])

    def test_raw_is_whitelisted(self):
        rows = collect.parse_usage({"five_hour": {"utilization": 5, "resets_at": None,
                                                  "access_token": "LEAK"}})
        self.assertNotIn("LEAK", rows[0][3])
        self.assertLessEqual(len(rows[0][3]), 500)


class FileCredsTests(Base):
    """Owner-hosted mode: tokens come from a Claude Code credentials file."""

    def setUp(self):
        super().setUp()
        self.cfg = os.path.join(self.tmp, "cfg")
        os.makedirs(self.cfg)
        self.cred = os.path.join(self.cfg, ".credentials.json")
        os.environ["CLAUDE_CONFIG_DIR"] = self.cfg
        self.write_creds()

    def write_creds(self, expires_in_s=3600, access=ACCESS, refresh=REFRESH):
        write(self.cred, json.dumps({
            "claudeAiOauth": {
                "accessToken": access, "refreshToken": refresh,
                "expiresAt": int((time.time() + expires_in_s) * 1000),
                "scopes": ["user:inference", "user:profile"],
                "subscriptionType": "max", "rateLimitTier": "default_claude_max_20x",
            },
            "otherTool": {"keep": "me"},
        }, indent=2))

    def creds(self):
        return json.loads(read(self.cred))

    def test_reads_file_and_plan(self):
        self.script([(200, SAMPLE)])
        rc, out, err = self.run_main()
        self.assertEqual(rc, 0)
        self.assertIn("status=ok", out)
        self.assertIn("creds=file", out)
        self.assertTrue(all(r["plan"] == "max" for r in self.rows()))
        self.assertEqual(self.calls, [("usage", ACCESS)])
        self.assert_no_secrets(out, err)

    def test_plan_falls_back_to_tier_then_env(self):
        d = self.creds()
        d["claudeAiOauth"]["subscriptionType"] = ""
        write(self.cred, json.dumps(d))
        self.script([(200, SAMPLE)])
        self.run_main()
        self.assertEqual(self.rows()[0]["plan"], "default_claude_max_20x")
        os.environ["CLAUDE_PLAN"] = "override"
        collect.CSV_PATH = self.csv = os.path.join(self.tmp, "other.csv")
        self.script([(200, SAMPLE)])
        self.run_main()
        self.assertEqual(self.rows()[0]["plan"], "override")

    def test_401_refreshes_and_writes_back_preserving_other_fields(self):
        self.script([(401, None), (200, SAMPLE)], NEW)
        rc, out, err = self.run_main()
        self.assertEqual([c[0] for c in self.calls], ["usage", "refresh", "usage"])
        self.assertEqual(self.calls[1][1], REFRESH)
        self.assertEqual(self.calls[2][1], "acc-NEW")
        d = self.creds()
        self.assertEqual(d["claudeAiOauth"]["accessToken"], "acc-NEW")
        self.assertEqual(d["claudeAiOauth"]["refreshToken"], "ref-NEW")
        self.assertEqual(d["claudeAiOauth"]["scopes"], ["user:inference", "user:profile"])
        self.assertEqual(d["otherTool"], {"keep": "me"})
        self.assertGreater(d["claudeAiOauth"]["expiresAt"], (time.time() + 3000) * 1000)
        self.assertFalse(os.path.exists(self.cred + ".tmp"))
        self.assertFalse(os.path.exists(os.path.join(self.cfg, ".oauth_refresh.lock")))
        self.assertEqual(len(self.rows()), 3)
        self.assert_no_secrets(out, err)

    def test_proactive_refresh_when_about_to_expire(self):
        self.write_creds(expires_in_s=30)
        self.script([(200, SAMPLE)], NEW)
        _, out, _ = self.run_main()
        self.assertEqual([c[0] for c in self.calls], ["refresh", "usage"])
        self.assertEqual(self.calls[1][1], "acc-NEW")
        self.assertIn("refreshed=true", out)
        self.assertEqual(self.creds()["claudeAiOauth"]["refreshToken"], "ref-NEW")

    def test_reuses_token_rotated_by_someone_else(self):
        """Claude Code refreshed between our read and our lock: use its token, do not refresh."""
        self.write_creds(expires_in_s=30)
        real_lock = collect.FileCreds._acquire_lock

        def racing_lock(fc):
            self.write_creds(expires_in_s=3600, access="acc-FROM-CLI", refresh="ref-FROM-CLI")
            return real_lock(fc)

        collect.FileCreds._acquire_lock = racing_lock
        try:
            self.script([(200, SAMPLE)], NEW)
            self.run_main()
        finally:
            collect.FileCreds._acquire_lock = real_lock
        self.assertEqual(self.calls, [("usage", "acc-FROM-CLI")])
        self.assertEqual(self.creds()["claudeAiOauth"]["refreshToken"], "ref-FROM-CLI")

    def test_lock_held_by_cli_writes_nothing(self):
        os.mkdir(os.path.join(self.cfg, ".oauth_refresh.lock"))
        self.script([(401, None)], NEW)
        _, out, _ = self.run_main()
        self.assertIn("refresh_lock_busy", out)
        self.assertEqual([c[0] for c in self.calls], ["usage"])
        self.assertEqual(self.creds()["claudeAiOauth"]["refreshToken"], REFRESH)
        self.assertEqual(self.rows(), [])

    def test_stale_cli_lock_is_taken_over(self):
        lk = os.path.join(self.cfg, ".oauth_refresh.lock")
        os.mkdir(lk)
        old = time.time() - 600
        os.utime(lk, (old, old))
        self.script([(401, None), (200, SAMPLE)], NEW)
        self.run_main()
        self.assertEqual(len(self.rows()), 3)
        self.assertFalse(os.path.exists(lk))

    def test_refresh_failure_leaves_file_untouched(self):
        before = read(self.cred)
        self.script([(401, None)], None)
        _, out, _ = self.run_main()
        self.assertIn("relogin_needed", out)
        self.assertEqual(read(self.cred), before)
        self.assertEqual(self.rows(), [])

    def test_no_refresh_flag(self):
        os.environ["CLAUDE_NO_REFRESH"] = "1"
        self.write_creds(expires_in_s=30)
        self.script([(401, None)], NEW)
        _, out, _ = self.run_main()
        self.assertEqual([c[0] for c in self.calls], ["usage"])
        self.assertIn("401_and_refresh_disabled", out)

    def test_missing_or_malformed_file(self):
        os.remove(self.cred)
        _, out, _ = self.run_main()
        self.assertIn("no_credentials", out)
        write(self.cred, "{not json")
        _, out, _ = self.run_main()
        self.assertIn("credentials_unreadable", out)
        write(self.cred, json.dumps({"claudeAiOauth": {"accessToken": 5}}))
        _, out, _ = self.run_main()
        self.assertIn("credentials_unreadable", out)
        self.assertEqual(self.rows(), [])

    def test_explicit_credentials_file_env_wins(self):
        other = os.path.join(self.tmp, "elsewhere.json")
        shutil.copy(self.cred, other)
        os.remove(self.cred)
        os.environ["CLAUDE_CREDENTIALS_FILE"] = other
        self.script([(200, SAMPLE)])
        _, out, _ = self.run_main()
        self.assertIn("status=ok", out)


class EnvCredsTests(Base):
    """Pattern A style: tokens from env vars, rotation written to CLAUDE_TOKEN_OUT."""

    def setUp(self):
        super().setUp()
        self.out = os.path.join(self.tmp, "rotated.json")
        os.environ.update(CLAUDE_ACCESS_TOKEN=ACCESS, CLAUDE_REFRESH_TOKEN=REFRESH,
                          CLAUDE_PLAN="max", CLAUDE_TOKEN_OUT=self.out)

    def test_happy_path_one_row_per_window(self):
        self.script([(200, SAMPLE)])
        rc, out, _ = self.run_main()
        self.assertEqual(rc, 0)
        self.assertIn("status=ok", out)
        self.assertIn("creds=env", out)
        rows = self.rows()
        self.assertEqual([r["window"] for r in rows], ["five_hour", "weekly_fable_5", "seven_day"])
        self.assertEqual(len({r["timestamp_utc"] for r in rows}), 1)
        self.assertEqual(rows[0]["usage_pct"], "37")

    def test_unrecognized_shape_writes_nothing(self):
        self.script([(200, {"surprise": 1})])
        rc, out, _ = self.run_main()
        self.assertEqual((rc, self.rows()), (0, []))
        self.assertIn("unrecognized_shape", out)

    def test_http_errors_write_nothing(self):
        for st in (0, 403, 429, 500):
            self.script([(st, None)])
            rc, _, _ = self.run_main()
            self.assertEqual((rc, self.rows()), (0, []))

    def test_401_refresh_retry_and_token_persisted(self):
        self.script([(401, None), (200, SAMPLE)], NEW)
        rc, out, err = self.run_main()
        self.assertEqual([c[0] for c in self.calls], ["usage", "refresh", "usage"])
        self.assertEqual(self.calls[2][1], "acc-NEW")
        saved = json.loads(read(self.out))
        self.assertEqual(saved, {"access_token": "acc-NEW", "refresh_token": "ref-NEW"})
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(self.out).st_mode), 0o600)
        self.assertEqual(len(self.rows()), 3)
        self.assert_no_secrets(out, err)

    def test_refresh_without_rotation_keeps_old_refresh_token(self):
        self.script([(401, None), (200, SAMPLE)], {"access_token": "acc-NEW"})
        self.run_main()
        self.assertEqual(json.loads(read(self.out))["refresh_token"], REFRESH)

    def test_refresh_failure_writes_nothing_and_does_not_loop(self):
        self.script([(401, None)], None)
        rc, out, _ = self.run_main()
        self.assertEqual((rc, self.rows()), (0, []))
        self.assertEqual([c[0] for c in self.calls], ["usage", "refresh"])
        self.assertIn("relogin_needed", out)

    def test_401_after_refresh_stops(self):
        self.script([(401, None), (401, None)], NEW)
        rc, out, _ = self.run_main()
        self.assertEqual((rc, self.rows()), (0, []))
        self.assertEqual(len(self.calls), 3)
        self.assertIn("401_after_refresh", out)

    def test_idempotent_within_two_minutes(self):
        self.script([(200, SAMPLE), (200, SAMPLE)])
        self.run_main()
        _, out, _ = self.run_main()
        self.assertIn("status=skipped", out)
        self.assertEqual(len(self.rows()), 3)

    def test_runs_again_after_gap_and_is_append_only(self):
        self.script([(200, SAMPLE), (200, SAMPLE)])
        self.run_main()
        old = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat(timespec="seconds")
        write(self.csv, read(self.csv).replace(self.rows()[0]["timestamp_utc"], old))
        before = read(self.csv)
        self.run_main()
        self.assertTrue(read(self.csv).startswith(before))
        self.assertEqual(len(self.rows()), 6)

    def test_run_lock_held_skips(self):
        write(collect.LOCK_PATH, "1")
        self.script([(200, SAMPLE)])
        _, out, _ = self.run_main()
        self.assertIn("reason=locked", out)
        self.assertEqual(self.rows(), [])

    def test_stale_run_lock_is_taken_over(self):
        write(collect.LOCK_PATH, "1")
        old = time.time() - 3600
        os.utime(collect.LOCK_PATH, (old, old))
        self.script([(200, SAMPLE)])
        self.run_main()
        self.assertEqual(len(self.rows()), 3)

    def test_no_credentials_at_all(self):
        for k in ENV_KEYS:
            os.environ.pop(k, None)
        os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(self.tmp, "nowhere")
        rc, out, _ = self.run_main()
        self.assertEqual((rc, self.rows()), (0, []))
        self.assertIn("no_credentials", out)


if __name__ == "__main__":
    unittest.main(verbosity=1)

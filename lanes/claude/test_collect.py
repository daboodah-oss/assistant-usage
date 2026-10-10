#!/usr/bin/env python3
"""Offline tests for collect.py (no network, no real tokens).  Run:
    python3 lanes/claude/test_collect.py
"""
import csv
import io
import json
import os
import stat
import sys
import tempfile
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


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.csv = os.path.join(self.tmp, "data", "claude", "usage.csv")
        self.out = os.path.join(self.tmp, "rotated.json")
        collect.CSV_PATH = self.csv
        collect.LOCK_PATH = os.path.join(self.tmp, "lock")
        collect._SECRETS.clear()
        for k in ("CLAUDE_ACCESS_TOKEN", "CLAUDE_REFRESH_TOKEN", "CLAUDE_PLAN",
                  "CLAUDE_TOKEN_OUT", "CLAUDE_NO_REFRESH"):
            os.environ.pop(k, None)
        os.environ.update(CLAUDE_ACCESS_TOKEN=ACCESS, CLAUDE_REFRESH_TOKEN=REFRESH,
                          CLAUDE_PLAN="max", CLAUDE_TOKEN_OUT=self.out)
        self.calls = []

    def script(self, usage_responses, refresh_response=(200, None)):
        usage_iter = iter(usage_responses)

        def fake_usage(tok):
            self.calls.append(("usage", tok))
            return next(usage_iter)

        def fake_refresh(rt):
            self.calls.append(("refresh", rt))
            return refresh_response[1]

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
        with open(self.csv, newline="") as f:
            return list(csv.DictReader(f))


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


class RunTests(Base):
    def test_happy_path_one_row_per_window(self):
        self.script([(200, SAMPLE)])
        rc, out, _ = self.run_main()
        self.assertEqual(rc, 0)
        self.assertIn("status=ok", out)
        rows = self.rows()
        self.assertEqual([r["window"] for r in rows], ["five_hour", "weekly_fable_5", "seven_day"])
        self.assertTrue(all(r["plan"] == "max" for r in rows))
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
        new = {"access_token": "acc-NEW", "refresh_token": "ref-NEW"}
        self.script([(401, None), (200, SAMPLE)], (200, new))
        rc, out, err = self.run_main()
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in self.calls], ["usage", "refresh", "usage"])
        self.assertEqual(self.calls[2][1], "acc-NEW")
        saved = json.load(open(self.out))
        self.assertEqual(saved, new)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(self.out).st_mode), 0o600)
        self.assertEqual(len(self.rows()), 3)
        for s in (ACCESS, REFRESH, "acc-NEW", "ref-NEW"):
            self.assertNotIn(s, out + err + open(self.csv).read())

    def test_refresh_without_rotation_keeps_old_refresh_token(self):
        self.script([(401, None), (200, SAMPLE)], (200, {"access_token": "acc-NEW"}))
        self.run_main()
        self.assertEqual(json.load(open(self.out))["refresh_token"], REFRESH)

    def test_refresh_failure_writes_nothing_and_does_not_loop(self):
        self.script([(401, None)], (200, None))
        rc, out, _ = self.run_main()
        self.assertEqual((rc, self.rows()), (0, []))
        self.assertEqual([c[0] for c in self.calls], ["usage", "refresh"])
        self.assertIn("relogin_needed", out)

    def test_401_after_refresh_stops(self):
        self.script([(401, None), (401, None)], (200, {"access_token": "a", "refresh_token": "b"}))
        rc, out, _ = self.run_main()
        self.assertEqual((rc, self.rows()), (0, []))
        self.assertEqual(len(self.calls), 3)  # usage, refresh, usage; no further retry

    def test_no_refresh_flag_never_rotates(self):
        os.environ["CLAUDE_NO_REFRESH"] = "1"
        self.script([(401, None)])
        self.run_main()
        self.assertEqual([c[0] for c in self.calls], ["usage"])
        self.assertFalse(os.path.exists(self.out))

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
        text = open(self.csv).read().replace(self.rows()[0]["timestamp_utc"], old)
        open(self.csv, "w").write(text)
        before = open(self.csv).read()
        self.run_main()
        self.assertTrue(open(self.csv).read().startswith(before))
        self.assertEqual(len(self.rows()), 6)

    def test_lock_held_skips(self):
        open(collect.LOCK_PATH, "w").write("1")
        self.script([(200, SAMPLE)])
        _, out, _ = self.run_main()
        self.assertIn("reason=locked", out)
        self.assertEqual(self.rows(), [])

    def test_stale_lock_is_taken_over(self):
        open(collect.LOCK_PATH, "w").write("1")
        old = datetime.now().timestamp() - 3600
        os.utime(collect.LOCK_PATH, (old, old))
        self.script([(200, SAMPLE)])
        self.run_main()
        self.assertEqual(len(self.rows()), 3)

    def test_missing_token_writes_nothing(self):
        os.environ["CLAUDE_ACCESS_TOKEN"] = ""
        rc, out, _ = self.run_main()
        self.assertEqual((rc, self.rows()), (0, []))
        self.assertIn("no_access_token", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)

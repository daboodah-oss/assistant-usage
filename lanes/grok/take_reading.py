#!/usr/bin/env python3
"""Take ONE Grok usage reading now (Grok feed redesign R8: one reading per wake).

Imports the box tracker (/workspace/grok-usage/grok_usage_tracker.py, box only, not in
this repo) and runs one poll under the tracker's POLL_LOCK, the same file lock the
tracker loop holds for every poll. The Grok login's refresh token rotates on use, so
two unlocked pollers could both refresh and burn each other's token; the shared lock
makes that impossible. The reading is appended to the tracker log like any loop poll.

If the tracker has no POLL_LOCK (unpatched copy), a one-shot is NOT safe: this script
falls back to waiting up to --wait seconds for the loop to produce a fresh reading,
and says so (R8 fallback).

Prints one line: READING ok age=<s> mode=<oneshot|wait> weekly=<pct> tier=<tier>
                 or READING fail mode=... reason=...
Never prints or reads token material itself. Exit 0 always (the caller decides).
Usage: take_reading.py [--tracker-dir DIR] [--wait 420] [--fresh 900]
"""
import argparse, importlib.util, json, os, sys, time
from datetime import datetime, timezone


def newest(log):
    try:
        with open(log, "rb") as f:
            f.seek(0, 2); n = f.tell(); f.seek(max(0, n - 65536))
            lines = [l for l in f.read().splitlines() if l.strip()]
        return json.loads(lines[-1]) if lines else None
    except Exception:
        return None


def age_s(rec):
    try:
        return int((datetime.now(timezone.utc) - datetime.fromisoformat(rec["ts"])).total_seconds())
    except Exception:
        return 10 ** 9


def report(mode, rec, extra=""):
    if rec and rec.get("ok"):
        print("READING ok mode=%s age=%ss weekly=%s tier=%s%s" % (
            mode, age_s(rec), rec.get("weekly_used_pct"), json.dumps(rec.get("tier")), extra))
    else:
        st = (rec or {}).get("status", "no_reading")
        print("READING fail mode=%s status=%s age=%ss%s" % (mode, st, age_s(rec) if rec else "-", extra))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracker-dir", default=os.environ.get("GROK_TRACKER_DIR", "/workspace/grok-usage"))
    ap.add_argument("--wait", type=int, default=420)
    ap.add_argument("--fresh", type=int, default=900)
    a = ap.parse_args()
    src = os.path.join(a.tracker_dir, "grok_usage_tracker.py")
    log = os.path.join(a.tracker_dir, "usage_log.jsonl")
    code = open(src).read() if os.path.exists(src) else ""
    if "POLL_LOCK" in code and "def poll_locked" in code:
        spec = importlib.util.spec_from_file_location("grok_usage_tracker", src)
        t = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(t)  # module import only; the loop/server start under __main__
        try:
            done = t.poll_locked(timeout=120)
        except Exception as e:
            print("READING fail mode=oneshot status=exception error=%s" % type(e).__name__); return 0
        rec = newest(log)
        report("oneshot", rec, "" if done else " note=lock_busy_used_loop_reading")
        return 0
    # R8 fallback: unpatched tracker, a one-shot could race the loop's token refresh.
    t0 = time.time()
    while True:
        rec = newest(log)
        if rec and age_s(rec) < a.fresh:
            report("wait", rec, " why=tracker_has_no_poll_lock"); return 0
        if time.time() - t0 > a.wait:
            report("wait", rec, " why=tracker_has_no_poll_lock stale"); return 0
        time.sleep(10)


if __name__ == "__main__":
    sys.exit(main())

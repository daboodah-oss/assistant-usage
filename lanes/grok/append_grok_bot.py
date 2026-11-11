#!/usr/bin/env python3
"""Append one window=grok_bot row to data/grok/usage.csv.

Leaves existing weekly / weekly_<product> rows untouched. Writes nothing
if usage_pct or reset_iso is missing or invalid — never a guessed zero.

Usage: append_grok_bot.py --pct 44.5 --reset 2026-11-16T03:53:00+00:00
"""
import argparse, csv, os, sys
from datetime import datetime, timezone, timedelta

DEFAULT_OUT = "/workspace/assistant-usage/data/grok/usage.csv"
HEADER = ["timestamp_utc", "usage_pct", "plan", "reset_iso", "window", "raw"]
MIN_GAP = timedelta(minutes=2)
PLAN = "SuperGrok Heavy"


def num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 100


def fmt(v):
    return ("%g" % round(float(v), 2))


def parse_reset(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        return None
    return dt


def last_grok_bot_ts(out):
    try:
        with open(out, newline="") as f:
            rows = list(csv.DictReader(f))
        for row in reversed(rows):
            if row.get("window") == "grok_bot":
                return datetime.fromisoformat(row["timestamp_utc"])
    except Exception:
        return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pct", required=True)
    ap.add_argument("--reset", required=True)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--plan", default=PLAN)
    a = ap.parse_args()
    try:
        pct = float(a.pct)
    except Exception:
        print("grok_bot append: usage_pct not a number -> no row")
        return 0
    if not num(pct):
        print("grok_bot append: usage_pct out of range -> no row")
        return 0
    reset_dt = parse_reset(a.reset)
    if reset_dt is None:
        print("grok_bot append: reset_iso missing or invalid -> no row")
        return 0
    reset = reset_dt.astimezone(timezone.utc).isoformat()
    ts = datetime.now(timezone.utc).replace(microsecond=0)
    prev = last_grok_bot_ts(a.out)
    if prev and (ts <= prev or ts - prev < MIN_GAP):
        print("grok_bot append: already have this sample (%s) -> skip" % prev.isoformat())
        return 0
    raw = (
        "source=grok_bot_usage weekly=%s%% "
        "(platform reading; percent and reset included when the reading is available, "
        "not omitted under 1%% the way the SuperGrok billing field is)" % fmt(pct)
    )[:500]
    row = [ts.isoformat(), fmt(pct), a.plan or PLAN, reset, "grok_bot", raw]
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    new = not os.path.exists(a.out) or os.path.getsize(a.out) == 0
    with open(a.out, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(HEADER)
        w.writerow(row)
    print("grok_bot append: 1 row (weekly=%s%%, reset=%s, plan=%s)" % (fmt(pct), reset, a.plan or PLAN))
    return 0


if __name__ == "__main__":
    sys.exit(main())

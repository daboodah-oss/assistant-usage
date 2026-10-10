#!/usr/bin/env python3
"""Grok lane collector (owner-hosted, docs/DEPLOYMENT.md pattern B).

Reads the newest reading from Ara's tracker log (/workspace/grok-usage/usage_log.jsonl)
and appends rows to data/grok/usage.csv per docs/DATA_CONTRACT.md:
  window=weekly             usage_pct = creditUsagePercent (tracker: weekly_used_pct)
  window=weekly_<product>   usage_pct = productUsage[] percent (tracker: products)
  reset_iso = billing currentPeriod.end (tracker: period_end), plan = tier.
Writes NOTHING (exit 0) if the newest reading is not ok, older than 20 min, or lacks the %.
Never reads or writes credentials. Stdlib only.
Usage: collect.py [--out PATH] [--log PATH]
"""
import argparse, csv, json, os, sys
from datetime import datetime, timezone, timedelta

DEFAULT_LOG = "/workspace/grok-usage/usage_log.jsonl"
DEFAULT_OUT = "/workspace/assistant-usage/data/grok/usage.csv"
HEADER = ["timestamp_utc", "usage_pct", "plan", "reset_iso", "window", "raw"]
MAX_AGE = timedelta(minutes=20)
MIN_GAP = timedelta(minutes=2)


def last_line(path):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 65536))
            lines = [l for l in f.read().splitlines() if l.strip()]
        return json.loads(lines[-1]) if lines else None
    except Exception:
        return None


def last_ts(out):
    try:
        with open(out, newline="") as f:
            rows = list(csv.DictReader(f))
        return datetime.fromisoformat(rows[-1]["timestamp_utc"]) if rows else None
    except Exception:
        return None


def num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 100


def fmt(v):
    return ("%g" % round(float(v), 2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--log", default=DEFAULT_LOG)
    a = ap.parse_args()
    rec = last_line(a.log)
    if not rec or not rec.get("ok") or not num(rec.get("weekly_used_pct")):
        print("grok collect: newest reading not ok / %% absent -> no row"); return 0
    try:
        ts = datetime.fromisoformat(rec["ts"]).astimezone(timezone.utc).replace(microsecond=0)
    except Exception:
        print("grok collect: bad ts -> no row"); return 0
    now = datetime.now(timezone.utc)
    if now - ts > MAX_AGE:
        print("grok collect: newest reading stale (%s) -> no row" % ts.isoformat()); return 0
    prev = last_ts(a.out)
    if prev and (ts <= prev or ts - prev < MIN_GAP):
        print("grok collect: already have this sample (%s) -> skip" % prev.isoformat()); return 0
    plan = rec.get("tier") or ""
    reset = rec.get("period_end") or ""
    pct = fmt(rec["weekly_used_pct"])
    prods = rec.get("products") or {}
    rows = [[ts.isoformat(), pct, plan, reset, "weekly",
             ("source=%s weekly=%s%% products=%s" % (rec.get("source"), pct,
              ",".join("%s:%s" % (k, fmt(v)) for k, v in sorted(prods.items()) if num(v))))[:500]]]
    for name, v in sorted(prods.items()):
        if num(v):
            rows.append([ts.isoformat(), fmt(v), plan, reset, "weekly_" + name,
                         ("product=%s %s%%" % (name, fmt(v)))[:500]])
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    new = not os.path.exists(a.out) or os.path.getsize(a.out) == 0
    with open(a.out, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(HEADER)
        w.writerows(rows)
    print("grok collect: appended %d rows (weekly=%s%%, plan=%s)" % (len(rows), pct, plan))
    return 0


if __name__ == "__main__":
    sys.exit(main())

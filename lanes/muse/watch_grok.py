#!/usr/bin/env python3
"""Off-box freshness watch for the grok lane (approved by Jeff 2026-11-15).

Budzilla-side, zero Grok cost: reads data/grok/usage.csv on main and
checks the age of the newest window=weekly row — the same signal the
dashboard's STALE badge uses (review R7). If that row is more than
2 hours old, prints one GROK WATCH ALERT line; the sampler cron
surfaces that line to Jeff. A state file suppresses repeats: one
alert per outage episode, keyed to the newest weekly row's
timestamp. Fetch failures stay silent — the next run retries in
15 minutes.

Why off-box: the Nov 14 outage proved that when the Grok Bot pool is
exhausted, Keela's box hibernates and nothing on the box can raise
an alarm. This watch runs on Budzilla's VM and survives that
failure. It also catches the quieter failure where commits land but
carry no weekly rows.
"""
import csv
import io
import json
import os
import urllib.request
from datetime import datetime, timezone

HOME = os.path.expanduser("~")
URL = ("https://raw.githubusercontent.com/daboodah-oss/"
       "assistant-usage/main/data/grok/usage.csv")
STATE = os.path.join(HOME, "workspace", "assistant-usage", "data",
                     "muse", ".grok_watch_state.json")
THRESHOLD_H = 2.0


def main():
    try:
        with urllib.request.urlopen(URL, timeout=30) as r:
            text = r.read().decode("utf-8", errors="replace")
    except Exception:
        return 0  # silent on network flakes; next run retries
    newest = None
    for row in csv.DictReader(io.StringIO(text)):
        if row.get("window") == "weekly" and row.get("timestamp_utc"):
            ts = row["timestamp_utc"]
            if newest is None or ts > newest:
                newest = ts
    if newest is None:
        return 0
    try:
        ts_dt = datetime.fromisoformat(newest.replace("Z", "+00:00"))
    except ValueError:
        return 0
    age_h = (datetime.now(timezone.utc) - ts_dt).total_seconds() / 3600.0
    state = {}
    if os.path.exists(STATE):
        try:
            with open(STATE) as f:
                state = json.load(f)
        except Exception:
            state = {}
    if age_h > THRESHOLD_H:
        if state.get("last_alerted_weekly_ts") != newest:
            print(f"GROK WATCH ALERT: newest weekly grok row on main is "
                  f"{newest} ({age_h:.1f}h old, threshold "
                  f"{THRESHOLD_H:.0f}h) — the grok feed may be down "
                  f"(box hibernated or pool exhausted).")
            state["last_alerted_weekly_ts"] = newest
            with open(STATE, "w") as f:
                json.dump(state, f)
    elif state.get("last_alerted_weekly_ts") is not None:
        state["last_alerted_weekly_ts"] = None
        with open(STATE, "w") as f:
            json.dump(state, f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

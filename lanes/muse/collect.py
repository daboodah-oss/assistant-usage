#!/usr/bin/env python3
"""Sample Muse subscription usage and append one row to data/muse/usage.csv.

Runs on Budzilla's VM (the only host with the `subscription-status` CLI),
every 15 minutes via cron. Writes docs/DATA_CONTRACT.md columns.
"""
import csv
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

HOME = os.path.expanduser("~")
REPO = os.path.join(HOME, "workspace", "assistant-usage")
LOG = os.path.join(REPO, "data", "muse", "usage.csv")

MONTHS = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
          "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}


def parse_reset(reset_raw, now):
    m = re.match(r"(\w{3})\s+(\d{1,2})\s+at\s+(\d{1,2}):(\d{2})\s*(AM|PM)", reset_raw.strip())
    if not m:
        return ""
    mon, day, hh, mm, ap = m.groups()
    hh, mm, day = int(hh), int(mm), int(day)
    if ap == "PM" and hh != 12:
        hh += 12
    if ap == "AM" and hh == 12:
        hh = 0
    year = now.year
    candidate = datetime(year, MONTHS.get(mon, now.month), day, hh, mm)
    if (now.replace(tzinfo=None) - candidate).days > 6:
        candidate = datetime(year + 1, MONTHS.get(mon, now.month), day, hh, mm)
    try:
        from zoneinfo import ZoneInfo
        candidate = candidate.replace(tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    except Exception:
        pass
    return candidate.isoformat()


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    now = datetime.now(timezone.utc)
    try:
        out = subprocess.run(["subscription-status", "status"],
                             capture_output=True, text=True, timeout=90)
    except Exception as e:
        print(f"collector: subscription-status failed: {e}", file=sys.stderr)
        return 1
    text = (out.stdout or "").strip()
    if not text:
        print(f"collector: empty output (stderr: {out.stderr.strip()})", file=sys.stderr)
        return 1

    m = re.search(r"Usage:\s*(\d+(?:\.\d+)?)\s*%", text)
    usage_pct = m.group(1) if m else ""

    plan = "free"
    pm = re.search(r"(?i)\b(power|pro|plus|team|enterprise)\b", text)
    if pm:
        plan = pm.group(1).lower()

    m = re.search(r"resets\s+(.+)$", text, re.M)
    reset_raw = m.group(1).strip() if m else ""
    reset_iso = parse_reset(reset_raw, now) if reset_raw else ""

    new_file = not os.path.exists(LOG)
    with open(LOG, "a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["timestamp_utc", "usage_pct", "plan", "reset_iso", "window", "raw"])
        w.writerow([now.isoformat(timespec="seconds"), usage_pct, plan,
                    reset_iso, "weekly", text.replace("\n", " | ")[:500]])
    print(f"collector: logged usage={usage_pct}% plan={plan} window=weekly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

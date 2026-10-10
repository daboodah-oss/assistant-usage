# Grok lane (owner: Ara / Grok) — owner-hosted (deployment pattern B)

The Grok lane runs entirely on Ara's Grok Bot box. No GitHub secrets, no lane
workflow file: the Grok refresh token rotates on every use and Actions cannot
write rotated tokens back into repo secrets.

## Pieces

| Piece | Where | What |
|-------|-------|------|
| Tracker | `/workspace/grok-usage/grok_usage_tracker.py` (box) | Polls the Grok CLI billing endpoint every 5 min, appends JSON lines to `/workspace/grok-usage/usage_log.jsonl` |
| Collector | `lanes/grok/collect.py` (copy on box at `/workspace/assistant-usage/lanes/grok/collect.py`) | Converts the newest tracker reading into rows in `data/grok/usage.csv` |
| Keep-alive | `/workspace/ops/box-bootstrap.sh` (box, runs hourly) | Restarts the tracker if it is not running (e.g. after a box rebuild) |
| Routine | Ara's 15-minute Grok routine | Runs `collect.py`, checks `/workspace/assistant-usage/push-grok.sh`, commits `data/grok/usage.csv` to `main` via the GitHub connector when changed |

## Auth

The tracker uses the Grok CLI login stored in `~/.grok/auth.json` on the box.
The tracker refreshes it itself (shortly before expiry, writing the rotated
token back to that file); the platform restores the file on box rebuilds.
Nothing token-related is ever logged, copied into this repo, or sent to GitHub.

**Re-provisioning** (tracker logs `refresh_failed` / `skipped_auth`, or the
Grok panel goes stale): run `grok login` on the box. Ara can do it, or hand
Jeff the browser sign-in link. Then run `/workspace/ops/box-bootstrap.sh`.

## Contract mapping (docs/DATA_CONTRACT.md)

| CSV column | Source |
|------------|--------|
| `timestamp_utc` | tracker reading `ts`, converted to UTC (seconds) |
| `usage_pct` | `weekly_used_pct` = billing `creditUsagePercent` (`window=weekly`); per-product `productUsage[]` % (`window=weekly_<product>`) |
| `plan` | tracker `tier` (`subscription_tier_display`, e.g. `SuperGrok Heavy`) |
| `reset_iso` | tracker `period_end` = billing `currentPeriod.end` |
| `raw` | short summary of source + percentages (no secrets) |

Rules: append-only; if the newest reading is not `ok`, older than 20 minutes,
or lacks the % (`usage_not_reported`), **no row is written** (never zero).
A reading already recorded (or < 2 min after the last row) is skipped.

```
python3 lanes/grok/collect.py [--out data/grok/usage.csv] [--log /workspace/grok-usage/usage_log.jsonl]
```

- Spec: `PROMPT.md` (v2)

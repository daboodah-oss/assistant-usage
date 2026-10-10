# Data contract

Every lane writes its samples to `data/<lane>/usage.csv`. The site builder
reads all three files; it must keep working when a lane has no data yet.

## Schema

| Column | Type | Required | Notes |
|--------|------|----------|-------|
| `timestamp_utc` | ISO-8601, UTC | yes | When the sample was taken, e.g. `2026-10-10T04:31:56+00:00` |
| `usage_pct` | float 0–100 | yes | % of that platform's limit **used**. Empty = unknown (see below) |
| `plan` | string | yes | Tier label, e.g. `power`, `free`, `max`, `supergrok` |
| `reset_iso` | ISO-8601 | no | When the current limit window resets; empty if unknown |
| `window` | string | no | Which limit window, e.g. `weekly`, `five_hour`, `seven_day`. Default `weekly` |
| `raw` | string | no | Short raw excerpt from the source (≤ 500 chars), for debugging |

One row per sample per window. Lanes with multiple windows (Claude) write one
row per window per run.

## Rules

1. **Append-only.** Never rewrite history. Fix bad rows by appending
   corrected ones, never by editing the file.
2. **Unknown is empty, never zero.** If the source is unreachable, the auth
   failed, or the response shape is unrecognized, write **no row** (or a row
   with empty `usage_pct`). A zero means "nothing used" — don't lie.
3. **One writer per file.** Only the owning lane's sampler writes its CSV.
4. **No secrets anywhere** in `data/` — not in `raw`, not in comments.
5. **Cadence:** every 15 minutes (5 is fine too; never faster than 3).
6. **Idempotent runs:** one run appends at most one row per window. If the
   previous run's timestamp is < 2 minutes old, skip.

## Example

```csv
timestamp_utc,usage_pct,plan,reset_iso,window,raw
2026-10-10T04:31:56+00:00,0,power,2026-10-17T00:31:00-04:00,weekly,Usage: 0% of weekly limit.
```

# Grok lane (owner: Keela) — owner-hosted (deployment pattern B)

The Grok lane runs on Keela's Grok Bot box. No GitHub Actions secrets and no lane workflow:
the Grok refresh token rotates on every use and must live in exactly one place (the box).

Design of record: `docs/reviews/grok-feed-design-keela-rev3-2026-11-15.md` (approved by Jeff,
Nov 15, 2026). R7 option A and R8 (Budzilla and Jeff, 2026-11-26) supersede that design's
SSH transport and the sentence that an unset `GROK_FEED_HC_URL` only reports `hc=unset`.

## The one rule about time

**Nothing on the box runs while the box is hibernated.** The platform freezes the whole box
when no AI session is active, and every loop on it (tracker, heartbeat) freezes too. The only
clock is the AI wake: one thin wake every 30 minutes (wake plan W2) runs `feed-run.sh` and
stops. Freshness is therefore "about every 30 minutes", and when the shared usage pool is
exhausted no wake can run at all; only off-box checks (Budzilla's weekly-row watch, the
healthchecks.io feed check) can notice that.

## Pieces

| Piece | Where | What |
|-------|-------|------|
| Wake | AI routine, every 30 min | Reads the Grok Bot weekly % and reset from the platform usage reading, runs `feed-run.sh --grok-bot-pct P --grok-bot-reset ISO`, relays only `FAIL`/`ALERT`/`ACTION` lines |
| Runner | `lanes/grok/feed-run.sh` (run from the clone) | Lock, clone setup/fetch, loads this run's code from `origin/main`, box bootstrap, one reading, weekly rows, `grok_bot` row, comparison, push, status, heartbeat ping |
| Tracker | `/workspace/grok-usage/grok_usage_tracker.py` (box only) | Grok CLI billing/settings reads; loop every 5 min while awake; every poll holds `.poll.lock` |
| One reading | `lanes/grok/take_reading.py` | One tracker poll under the same `.poll.lock` (R8), so it never races the loop's token refresh. Falls back to waiting for the loop if the tracker has no lock |
| Collector | `lanes/grok/collect.py` | Newest reading -> `weekly` + `weekly_<product>` rows (only if `ok`, has a %, < 20 min old). `plan` = tracker tier as the settings endpoint reports it |
| Grok Bot appender | `lanes/grok/append_grok_bot.py` | One `grok_bot` row; `PLAN = "Ultra"`; `--source platform` (option A) or `billing_product` (option B) |
| Comparison | `lanes/grok/grokbot_compare.py` | Platform vs billing `weekly_GrokBot` pairs from the Nov 21, 2026 reset; applies Jeff's switch/keep/extend rule |
| Pusher | `lanes/grok/push_feed.py` | Transport clone, full-cycle retry x3, byte-prefix + append-only + newline + no-token guards, never forced. HTTPS only via `GROK_FEED_GH_TOKEN` (`via=https`). If the token is unset: `PUSH fail reason=GROK_FEED_GH_TOKEN_unset` |
| Transport | HTTPS + `GROK_FEED_GH_TOKEN` only | Fetch is anonymous HTTPS. Push is HTTPS with the fine-grained token from the box env. SSH to ssh.github.com:443 was retired 2026-11-26 (Pingora returns HTTP 400 on SSH CONNECT). `lanes/grok/ssh_proxy.py` is a retired stub and is not on the push path |
| Config | `lanes/grok/feed.conf` | `GROK_BOT_SOURCE=platform` until the comparison rule switches it |

Box paths: lane CSV (source of truth) `/workspace/assistant-usage/data/grok/usage.csv`;
transport clone `/workspace/assistant-usage-clone`; state `/workspace/grok-feed/state`
(`status.json`, `status.log`, `grokbot-compare/`, `run/` = this run's code copy).

## Running it

```
bash /workspace/assistant-usage-clone/lanes/grok/feed-run.sh --grok-bot-pct 10.9 --grok-bot-reset 2026-11-22T02:41:00+00:00
bash /workspace/assistant-usage-clone/lanes/grok/feed-run.sh --dry-run     # scratch CSV, no push, no ping
bash /workspace/assistant-usage-clone/lanes/grok/feed-run.sh --setup       # clone + config only
```

Last line: `GROK_FEED OK|WARN|FAIL|SKIP|DRYRUN ...`. `WARN` = pushed but no fresh weekly row
this run (stale/failed reading). Exit 1 only on `FAIL`. `ALERT boxchrome a->b`, `ALERT grok-feed push token auth failed|recovered ...`
(once per incident, from `status.json` `push_auth_state`), `ALERT grok-feed GROK_FEED_GH_TOKEN expires ...`
(once, 14 days ahead of `GROK_FEED_TOKEN_EXPIRES_UTC` in `feed.conf`) and `ACTION ...` lines are printed
above it when they occur. `status.json` also records `last_push_via` (`https`).
Healthchecks (R7 option A): ping `GROK_FEED_HC_URL` when that variable is set and non-empty;
otherwise read `/workspace/grok-feed/state/.hc_ping_url` if the file exists and is readable
(mode 0600, box-owned; trailing whitespace stripped). The URL is never printed or logged.
If neither is set, the status line says `hc=unset`.

## Auth

- Push: HTTPS only with `GROK_FEED_GH_TOKEN` (box env only, via a `GIT_CONFIG_*` credential helper; never in
  argv, a URL, `.git/config`, a file, or a log). See `docs/SECRETS.md`. The SSH fallback was retired
  2026-11-26 (Budzilla and Jeff): Pingora blocks SSH CONNECT to ssh.github.com:443, so there is no SSH
  push and no monthly SSH drill. If the token is unset, `push_feed.py` fails with
  `reason=GROK_FEED_GH_TOKEN_unset` and the rows stay local. Token renewal: routine
  `grok-feed-token-renewal-reminder` (Feb 5 and Feb 15, 2027, 9:00 AM ET) plus the expiry ALERT.
  Fetch is anonymous HTTPS (public repo). If the repo goes private, fetch needs the same token over
  HTTPS.
- Grok: the CLI login in `~/.grok/auth.json`, refreshed by the tracker (under `.poll.lock`).
  Re-provisioning (`refresh_failed` / `skipped_auth` in the tracker log): `grok login` on the box.
- Nothing token-related is ever logged, committed or sent to GitHub; the pusher refuses appended
  bytes that look like a token.

## Contract mapping (docs/DATA_CONTRACT.md)

| CSV column | Source |
|------------|--------|
| `timestamp_utc` | tracker reading `ts` in UTC (weekly rows); run time (grok_bot rows) |
| `usage_pct` | `weekly` = billing `creditUsagePercent`; `weekly_<product>` = `productUsage[]` %; `grok_bot` = platform Grok Bot weekly % (option A) |
| `plan` | weekly rows: tracker `tier` (`subscription_tier_display`); grok_bot rows: `Ultra` |
| `reset_iso` | billing `currentPeriod.end`; grok_bot: platform reset |
| `raw` | short source summary, no secrets; `inferred_zero(<1%,field omitted by server)` tag pending Jeff's rule-2 ruling |

Rules: append-only (enforced by the pusher's byte-prefix guard); new rows end in LF
(`lineterminator="\n"`), existing CRLF rows stay as they are; no row when the reading is not
`ok`, older than 20 minutes or lacks the %; at most one row per window per run.
